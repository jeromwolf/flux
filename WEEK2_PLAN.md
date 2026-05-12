# Flux — Week 2 작업 지시서

## 목표
W1에서 만든 "1회 실행 + cron 스케줄" 위에 **24/7 운영에 필요한 안전망**을 얹는다.
**완료 기준:** 2~3개 에이전트를 동시에 데몬으로 띄우고, (1) 의도적 실패를 Watchdog이 자동 복구하고, (2) 월간 비용 한도를 넘기면 자동 차단하며, (3) 재시작해도 일/월간 비용 누적이 유지된다.

## 현재 상태 (W1 종료 시점)
- `flux start -d --now` 데몬 실행 가능 (포그라운드 BlockingScheduler 1프로세스 = 1에이전트)
- `SafetyShield`는 **메모리 기반** — 프로세스 재시작 시 일/월간 카운터 0으로 초기화됨 ❌
- `AgentScheduler`는 `misfire_grace_time`, `max_instances` 미설정 — 중복 실행/유실 가능 ❌
- `watchdog.py` 없음 ❌
- 실패 시 backoff 없이 다음 cron까지 무한 대기

## W2 핵심 변경 사항 한눈에

| 모듈 | W1 상태 | W2 후 |
|---|---|---|
| `safety/shield.py` | 메모리 카운터 | 디스크 영속화(`~/.flux/agents/<name>/budget_state.json`) + 임계 경고(80/95%) + 비상 차단 플래그 |
| `scheduler.py` | 기본 cron 트리거 | `misfire_grace_time=300s`, `max_instances=1`, 실패 backoff, 다음 실행 시각 영속화 |
| `watchdog.py` | 없음 | **신규.** PID/하트비트/마지막 실행 시각 감시 + exponential backoff 재시작 + 알림 훅 |
| `runner.py` | shield 매 실행마다 새로 생성 | 데몬 라이프타임 동안 shield 단일 인스턴스 재사용 + 디스크 상태 로드/저장 |
| `cli.py` | 7개 명령 | + `flux watch <file>` (Watchdog 단독 실행), `flux status <name>` (헬스 요약) |

---

## Day 8-9: Watchdog 모듈 (신규)

### 책임
1. **헬스체크**: PID 살아있는지, `last_run_at` 임계 시간 이내인지, `agent.log`에서 최근 ERROR 빈도
2. **자동 복구**: 죽었으면 `flux start -d`로 재시작. 실패 횟수에 따라 exponential backoff (30s → 1m → 5m → 15m → 30m, 최대 30분 천장)
3. **알림 훅**: 복구 시도/실패/비용 임계 도달 시 후크 호출 (MVP는 stdout + `~/.flux/agents/<name>/events.jsonl` 기록)

### 파일 추가
```
src/flux/watchdog.py            # AgentWatchdog 클래스
~/.flux/agents/<name>/heartbeat.json   # runner가 매 실행 후 갱신
~/.flux/agents/<name>/events.jsonl     # watchdog 이벤트 로그
```

### `heartbeat.json` 스키마
```json
{
  "agent_name": "news-bot",
  "last_run_at": "2026-05-12T08:00:12+09:00",
  "last_run_status": "success",
  "last_error": null,
  "next_run_at": "2026-05-13T08:00:00+09:00",
  "consecutive_failures": 0
}
```

### `AgentWatchdog` API
```python
class AgentWatchdog:
    def __init__(self, runner: AgentRunner, check_interval: int = 60): ...
    def is_healthy(self) -> tuple[bool, str]: ...    # (ok, reason)
    def restart(self) -> bool: ...                    # exponential backoff 적용
    def watch_forever(self) -> None: ...              # blocking 루프
    def emit_event(self, event_type: str, data: dict) -> None: ...
```

### 검증
- `pytest tests/test_watchdog.py` — 6개 테스트
- 통합: 에이전트 중간에 `kill -9` → 60초 이내 자동 재시작

---

## Day 10-11: Safety Shield 강화

### 변경점

#### 1. 영속화 (가장 중요)
```python
# 신규: ~/.flux/agents/<name>/budget_state.json
{
  "daily_cost": 0.045,
  "daily_reset_date": "2026-05-12",
  "monthly_cost": 1.234,
  "monthly_reset_month": "2026-05"
}
```
- `BudgetTracker.load_from_disk(path)` / `save_to_disk(path)` 추가
- `SafetyShield.record_success()` 호출 시마다 자동 저장 (atomic write: tmp → rename)

#### 2. 임계 경고 (Soft Threshold)
- daily/monthly의 80%, 95% 도달 시 경고 이벤트 발생 (Watchdog의 알림 훅에 전달)
- pre_check는 통과시키되 `(True, "WARNING: daily 95%")` 같은 메시지 반환 → runner가 로그+이벤트로 기록

#### 3. 비상 차단 (Hard Kill Switch)
- `~/.flux/agents/<name>/emergency_stop` 파일 존재 시 pre_check 즉시 False
- CLI: `flux halt <name>` / `flux resume <name>`로 토글

### 변경 파일
- `src/flux/safety/shield.py` — `BudgetTracker` 영속화 메서드, 임계 경고, `EMERGENCY_STOP` 체크
- `src/flux/runner.py` — shield 인스턴스를 `__init__`에서 1회 생성, 디스크 로드, 매 실행 후 저장
- `src/flux/cli.py` — `halt`/`resume` 명령 추가

### 검증
- `pytest tests/test_shield.py` — 기존 12개 + 신규 6개 (영속화/임계/비상차단)
- 통합: 데몬 실행 중간에 프로세스 재시작 → 일간 비용 누적 유지 확인

---

## Day 12: Scheduler 견고화

### 변경점

```python
# scheduler.py 변경
self.scheduler.add_job(
    self._run_agent,
    trigger=trigger,
    id=f"agent-{self.runner.name}",
    name=f"Agent: {self.runner.name}",
    replace_existing=True,
    misfire_grace_time=300,       # 5분 이내 미스파이어는 따라잡음
    max_instances=1,              # 중복 실행 절대 금지
    coalesce=True,                # 밀린 실행은 1회로 통합
)
```

### 추가
- **실패 backoff 어댑터**: 연속 N회 실패 시 다음 cron까지 기다리지 말고 `min(2^n, 30분)` 후 1회 재시도 한 다음 정상 cron으로 복귀
- **종료 hook**: SIGTERM 받으면 진행 중인 실행을 최대 30초 grace 후 종료
- **next_run 영속화**: `heartbeat.json`의 `next_run_at` 갱신

### 검증
- `pytest tests/test_scheduler.py` — 신규 5개 테스트 (misfire, coalesce, max_instances)

---

## Day 13: 멀티 에이전트 통합 검증

### 시나리오 (10단계)
1. `flux init bot-a` / `flux init bot-b` (둘 다 5분 cron)
2. `flux start agents/bot-a.yaml -d --now`
3. `flux start agents/bot-b.yaml -d --now`
4. `flux list` → 둘 다 running
5. `flux watch agents/bot-a.yaml -d` (Watchdog 데몬 별도 띄움)
6. `bot-a` 프로세스를 `kill -9` → 60초 이내 자동 재시작 확인
7. `flux halt bot-b` → 다음 실행 즉시 차단 확인
8. `flux resume bot-b` → 정상 복귀
9. `bot-a`를 강제로 비용 한도 초과시킨 후 재시작 → 누적 유지 확인 (영속화)
10. `flux stop bot-a` / `flux stop bot-b` / `flux unwatch bot-a` 정상 종료

### 신규 의존성
- 없음 (APScheduler/click/rich/pydantic으로 충분)

---

## Day 14: 문서 갱신 + 커밋

### 문서
- `CLAUDE.md` Week 2 섹션을 "완료" 상태로 업데이트
- `README.md`에 "Safety + Watchdog" 섹션 추가 (GIF는 W4에서 추가)

### 커밋 단위
1. `feat(safety): BudgetTracker 디스크 영속화 + 임계 경고 + 비상 차단`
2. `feat(scheduler): misfire/coalesce/max_instances + 실패 backoff`
3. `feat(watchdog): AgentWatchdog 모듈 + heartbeat/events 로그`
4. `feat(cli): halt/resume/watch/status 명령 추가`
5. `test: Week 2 테스트 18개 추가 (총 75개)`
6. `docs: Week 2 완료 — 24/7 안전망 구축`

---

## 테스트 목표
- W1 종료 시점: 57개
- W2 종료 시점: **75개 (+18개)**
  - watchdog: 6개
  - shield 영속화/임계: 6개
  - scheduler 강건화: 5개
  - cli halt/resume: 1개

## 참고
- W1 작업 지시서: `./WEEK1_PLAN.md`
- 운영 경험 원본: `/Users/blockmeta/Desktop/workspace/flux-openclaw/` (현재 7개 에이전트 월 ~$1.26로 운영)
- 보안/안전 레이어 원본 모듈: `flux-openclaw/openclaw/{cost_tracker.py, resilience.py}`
