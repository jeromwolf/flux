# Flux — AI 에이전트 런타임 플랫폼

## 1. 프로젝트 개요

**Flux**는 "누구나 AI 에이전트를 만들고, 배포하고, 24/7 돌리는 플랫폼"입니다.

> "Cursor가 코드를 짜게 해줬다면, Flux는 에이전트가 일하게 해준다"

- **도메인**: flux.ai.kr
- **GitHub**: jeromwolf/flux
- **라이선스**: Apache 2.0

### 왜 만드는가?
- AI 에이전트를 만드는 도구(CrewAI, LangGraph)는 넘치지만, 안전하게 24/7 운영하는 인프라는 없다
- 에이전트 프로젝트의 88%가 프로덕션에서 실패 — 모델 능력 부족이 아니라 운영 인프라 부재
- $47,000 비용 폭주, 보안 사고 88%, 런타임 가시성 보유 기업 21%뿐

### 시장 규모 (2026년 5월 기준)
- **2025 시장**: $7.84B (MarketsandMarkets)
- **2030 예측**: $52.62B (CAGR 46.3%)
- **2025 에이전트 투자**: $6.42B (역대 최대, 전년 대비 69%↑)
- **2026 Q1 투자**: $2.66B (전년 동기 대비 144%↑, 평균 라운드 $155M)
- **AI 전체 VC (2025)**: $211B (+85% YoY)
- **Cursor**: SpaceX $60B 인수 옵션 (3.5년 만에, IPO 후 확정)
- **Sierra AI**: $15B 밸류에이션, $950M 라운드 (2026.05)

### 우리의 무기
Kelly(개발자)는 flux-openclaw에서 이미 **7개 자율 에이전트를 월 ~$1.26로 24/7 운영 중**이다.
이 실전 운영 경험을 제품화하는 것이 핵심이다.

**현재 포트폴리오 (2026.05.07):**
- coinclaw (Korbit 암호화폐): ₩1,902,105 (P&L +₩120,751)
- stockclaw (미국 주식): $1,034.18 (P&L +$72.23)
- korclaw (한국 ETF): ₩300,234 (신규)
- 총 자산: ₩3,513,450 | 총 수익: ₩225,288 (+6.67%)

---

## 2. 기술적 출발점: flux-openclaw

flux-openclaw는 Kelly의 개인 AI 에이전트 시스템이다. 여기서 코어 모듈을 추출하여 Flux 제품을 만든다.

**원본 위치**: `/Users/blockmeta/Desktop/workspace/flux-openclaw/`

### 추출 대상 모듈 (7개)

| 원본 파일 | 줄 수 | Flux 대상 | 역할 |
|-----------|-------|-----------|------|
| `openclaw/conversation_engine.py` | 740줄 | `src/flux/engine.py` | 에이전트 실행 엔진 (도구 사용 루프, 재시도, 타임아웃) |
| `openclaw/llm_provider.py` | 1075줄 | `src/flux/llm.py` | LLM 추상화 (Anthropic/OpenAI/Google) |
| `core.py` | 73줄 | `src/flux/tools/manager.py` | ToolManager (도구 로드, 보안 스캔, 핫 리로드) |
| `openclaw/cost_tracker.py` | 118줄 | `src/flux/safety/shield.py` | 비용 추적 + 하드리밋 + Circuit Breaker |
| `openclaw/resilience.py` | 174줄 | `src/flux/core/resilience.py` | 재시도, 타임아웃 처리 |
| `config.py` | 234줄 | `src/flux/config.py` | 설정 관리 (환경변수 > config.json > 기본값) |
| `logging_config.py` | 156줄 | `src/flux/logging.py` | 구조화 로깅 + 비밀 마스킹 |

### 추출 대상 도구 (기본 내장용)

원본 위치: `/Users/blockmeta/Desktop/workspace/flux-openclaw/tools/`

| 도구 파일 | Flux 포함 여부 | 용도 |
|-----------|---------------|------|
| `web_search.py` | 포함 | 인터넷 검색 |
| `web_fetch.py` | 포함 | 웹 페이지 가져오기 (SSRF 방어 포함) |
| `read_text_file.py` | 포함 | 파일 읽기 |
| `save_text_file.py` | 포함 | 파일 저장 (경로 보안) |
| `list_files.py` | 포함 | 디렉토리 목록 |
| `memory_manage.py` | 포함 | 에이전트 메모리 |
| `schedule_task.py` | 포함 | 예약 작업 |
| `weather.py` | 선택 | 날씨 예제 |
| 나머지 | 제외 | 트레이딩/마켓 특화 도구 |

### 추출 시 수정 사항

1. **멀티테넌트 준비**: 하드코딩된 경로 → 유저별 격리 경로
2. **클래스 리네임**: ConversationEngine → AgentEngine
3. **의존성 최소화**: 트레이딩 관련 import 제거
4. **BYOK 모델**: 유저가 자기 API 키 사용 (LLM 비용 $0)
5. **보안 스캔 유지**: AST 분석 + 위험 패턴 탐지 그대로

---

## 3. 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                      Web UI (Next.js)                       │
│   [에이전트 빌더]  [대시보드]  [Agent Store]  [설정]        │
└────────────────────────────┬──────────────────────────────┘
                             │ REST API
┌────────────────────────────▼──────────────────────────────┐
│                    API Gateway (FastAPI)                    │
│   [인증]  [Rate Limit]  [라우팅]  [WebSocket]              │
└────────────────────────────┬──────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Agent Engine │  │  Safety Shield   │  │   Scheduler      │
│  (실행 엔진)  │  │  (안전 레이어)   │  │  (스케줄러)      │
│              │  │                  │  │                  │
│ • AgentEngine│  │ • 비용 하드리밋  │  │ • Cron 스케줄    │
│ • ToolManager│  │ • AST 보안스캔   │  │ • 이벤트 트리거  │
│ • LLM 추상화│  │ • 샌드박스       │  │ • 큐 관리        │
│ • 메모리     │  │ • 자동 차단기    │  │ • 동시성 제어    │
└──────┬───────┘  └──────────────────┘  └──────────────────┘
       │
┌──────▼───────┐  ┌──────────────────┐  ┌──────────────────┐
│   Watchdog   │  │    Observatory   │  │    Agent Store   │
│  (자동 복구) │  │   (모니터링)     │  │  (마켓플레이스)  │
└──────────────┘  └──────────────────┘  └──────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│                    Database Layer                            │
│   [PostgreSQL: 유저/에이전트/실행로그]  [Redis: 큐/캐시]    │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 프로젝트 구조 (목표)

```
flux/
├── pyproject.toml              # Python 패키지 (pip install flux-agent)
├── README.md                   # OSS README (GIF 데모, Quick Start)
├── LICENSE                     # Apache 2.0
├── .env.example                # 환경변수 템플릿
├── CLAUDE.md                   # 이 파일
├── WEEK1_PLAN.md               # Week 1 상세 작업 지시서
├── src/
│   └── flux/
│       ├── __init__.py
│       ├── cli.py              # CLI (flux init/start/stop/list/logs/cost)
│       ├── engine.py           # 에이전트 실행 엔진
│       ├── llm.py              # LLM 추상화 (Anthropic/OpenAI/Google)
│       ├── config.py           # 설정 관리
│       ├── logging.py          # 구조화 로깅
│       ├── core/
│       │   ├── __init__.py
│       │   └── resilience.py   # 재시도, 타임아웃
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── manager.py      # ToolManager (보안 스캔 + 핫 리로드)
│       │   └── builtins/       # 기본 도구 (web_search, web_fetch 등)
│       ├── safety/
│       │   ├── __init__.py
│       │   ├── shield.py       # Safety Shield (비용 하드리밋 + Circuit Breaker)
│       │   └── scanner.py      # 도구 보안 스캔 (AST 분석)
│       ├── scheduler.py        # APScheduler 기반 스케줄러
│       └── watchdog.py         # 에이전트 헬스체크 + 자동 복구
├── agents/
│   └── examples/
│       └── news-summary.yaml   # 예제 에이전트
├── tests/
│   └── ...
└── docs/
    └── ...
```

---

## 5. agent.yaml 포맷

에이전트는 YAML 파일로 정의한다:

```yaml
name: news-summary-bot
description: "매일 아침 AI 뉴스를 요약해서 정리"

# 실행 설정
schedule: "0 8 * * *"           # cron: 매일 08:00
model: claude-haiku              # LLM 모델
max_tokens: 4096

# 안전 설정
budget:
  per_run: 0.10                  # 실행당 최대 $0.10
  daily: 1.00                   # 일일 최대 $1.00
  monthly: 10.00                # 월간 최대 $10.00

# 도구 (허용 목록)
tools:
  - web_search
  - web_fetch

# 프롬프트
system_prompt: |
  당신은 AI/테크 뉴스 큐레이터입니다.
  매일 주요 AI 뉴스 5개를 찾아 한국어로 요약합니다.

user_prompt: |
  오늘의 AI 뉴스 Top 5를 검색하고 각 뉴스를 2~3문장으로 요약해주세요.
```

---

## 6. CLI 명령어

```bash
flux init <name>             # agent.yaml 템플릿 생성
flux validate <file>         # agent.yaml 유효성 검증
flux start <file>            # 에이전트 실행 (포그라운드)
flux start <file> -d         # 에이전트 실행 (데몬)
flux stop <name>             # 에이전트 중지
flux list                    # 실행 중인 에이전트 목록
flux logs <name>             # 에이전트 로그 보기
flux cost <name>             # 비용 요약
```

---

## 7. 4주 MVP 로드맵

| 주차 | 목표 | 완료 기준 |
|------|------|-----------|
| **W1** | 코어 엔진 추출 + CLI | `flux start`로 뉴스 요약 봇 1개 실행 성공 |
| **W2** | 스케줄러 + Watchdog + Safety Shield | 스케줄 자동 실행, 장애 자동 복구, 비용 초과 자동 중단 |
| **W3** | Next.js 웹 UI + FastAPI + 인증 | 웹에서 에이전트 생성/배포/모니터링 |
| **W4** | 독푸딩 + OSS 공개 + HN 런칭 | GitHub public, Show HN 포스트, 첫 외부 유저 |

**현재: Week 2 완료 — Watchdog/Shield 영속화/Scheduler 강건화, 81개 테스트 올그린 ✓**

---

## 8. Week 2 완료 (24/7 안전망)

### Day 8-9: Watchdog 모듈 ✅
- `src/flux/watchdog.py` 신규 (`AgentWatchdog` 클래스)
- 헬스체크 3종: 프로세스 생존, 하트비트 신선도, 연속 실패 카운트
- exponential backoff 재시작 (30s → 60s → 5m → 15m → 30m 천장)
- `~/.flux/agents/<name>/heartbeat.json` + `events.jsonl` 영속화
- `flux watch <file>` / `flux unwatch <name>` / `flux status <name>` CLI 추가

### Day 10-11: Safety Shield 강화 ✅
- `BudgetTracker` 디스크 영속화 (`budget_state.json`, atomic write)
- 일/월 임계 경고 (80%, 95%) — `SafetyShield.get_warnings()`
- 비상 차단: `emergency_stop` 파일 + `flux halt` / `flux resume` CLI
- `record_success()` 호출 시 자동 디스크 저장 → 데몬 재시작해도 누적 유지

### Day 12: Scheduler 견고화 ✅
- `misfire_grace_time=300`, `max_instances=1`, `coalesce=True` 기본 적용
- 데몬 시작 시 `mark_started()`로 하트비트 부트스트랩
- 실행 후 다음 cron `next_run_at` 하트비트 동기화 (Watchdog freshness anchor)
- 실패 backoff는 Watchdog에 위임 (책임 분리)

### Day 13: 통합 검증 ✅
- CLI 통합: `halt`/`resume`/`status`/`watch`/`unwatch` 5개 명령 E2E 동작 확인
- 단위: heartbeat 라이프사이클, corrupt 파일 안전 회복, budget 영속화 round-trip

### Day 14: 문서 + 커밋 ✅
- README.md: "24/7 Operation Recipe" 섹션 추가, CLI 표/Features 갱신
- CLAUDE.md: W2 완료 마킹

### W2 테스트 (57 → 81, +24개)
- `test_watchdog.py` 신규 6개 (헬스체크 4 + backoff 1 + event log 1)
- `test_shield.py` +6 (영속화 3 + 비상차단 1 + 임계 경고 2)
- `test_scheduler.py` 신규 5개 (defaults/cron parser/overrides/hardening flags)
- `test_cli.py` +5 (halt/resume/status/help)
- `test_runner.py` +2 (heartbeat 라이프사이클, corrupt 회복)

---

## 9. Week 1 상세 (이전 작업)

### Day 1-2: 프로젝트 구조 + 코어 추출 ✅
- pyproject.toml 셋업
- flux-openclaw에서 8개 코어 모듈 추출 + 정리
- 7개 builtin tools 추출
- 의존성 최소화

### Day 3-4: agent.yaml + CLI ✅
- agent.yaml 로더 + 검증 (pydantic AgentConfig)
- CLI 7개 명령어 구현 (click + Rich)
- AgentRunner 클래스
- AgentScheduler (APScheduler 데몬 모드)

### Day 5: 통합 테스트 + 실행 성공 ✅
- Python 3.12 venv 환경 셋업
- 뉴스 요약 봇 실행 성공 ($0.014/run, 30초)
- 모델 ID 최신화, content 직렬화 수정
- GitHub 첫 커밋

### Day 6: 테스트 작성 ✅
- pytest 57개 테스트 작성 (6개 파일)
- test_config (10), test_shield (12), test_scanner (8), test_runner (10), test_cli (8), test_resilience (9)
- BudgetTracker 날짜 초기화 버그 발견 및 수정

### Day 7: 데몬 모드 검증 + 10단계 시나리오 완료 ✅
- `flux start -d --now` 데몬 모드 실행 성공
- 10단계 검증 시나리오 전체 통과 (init → validate → start → cost → daemon → list → logs → cost → stop)
- scheduler.py 로깅 포맷 버그 수정

### 의존성

```
anthropic>=0.45.0
openai>=1.60.0         # 선택
httpx>=0.27.0
apscheduler>=3.10.0
click>=8.1.0           # CLI
pyyaml>=6.0
rich>=13.0             # 터미널 UI
pydantic>=2.0          # 설정 검증
```

---

## 10. 기술 스택

| 항목 | 선택 | 이유 |
|------|------|------|
| 언어 | Python 3.11+ | flux-openclaw 그대로 |
| API | FastAPI | 동일 |
| DB | SQLite → PostgreSQL | MVP는 SQLite, 프로덕션은 PG |
| 큐 | Redis (선택) | MVP는 in-memory |
| UI | Next.js (Week 3) | 모던 React |
| CLI | Click + Rich | 개발자 친화적 |
| 배포 | Fly.io / Railway | 저비용 |
| CI | GitHub Actions | 표준 |

---

## 11. 비즈니스 모델

| 플랜 | 가격 | 내용 |
|------|------|------|
| Free | $0 | 에이전트 1개, 일 10회 실행 |
| Pro | $29/월 | 에이전트 10개, 무제한 실행 |
| Team | $99/시트/월 | 팀 협업, API |
| Enterprise | 커스텀 | 온프레미스, SLA |

BYOK 모델: 유저가 자기 API 키 사용 → LLM 비용 $0, 인프라 월 $10~15

---

## 12. 킬러 피처 (경쟁 차별화)

1. **Safety Shield**: $47K 비용 폭주를 원천 차단하는 하드리밋 + 자동 차단기 (경쟁사 없음)
2. **Watchdog Runtime**: 에이전트 장애 시 5분 내 자동 복구 (실전 검증됨)
3. **Agent Store**: 만든 에이전트를 공유/판매하는 마켓플레이스 (네트워크 효과)

---

## 13. 경쟁사

| 경쟁사 | 약점 | 우리의 우위 |
|--------|------|-------------|
| CrewAI ($18M) | 빌드 도구일 뿐, 운영 인프라 없음 | Runtime + Safety |
| Sierra AI ($15B, $950M) | 엔터프라이즈 전용, 고가 | $0 시작, 개인/SMB |
| Relevance AI | 비용 폭주 방지 없음 | Safety Shield |
| Lovable ($20M ARR) | "만들기"에서 끝남 | 24/7 운영 |
| Salesforce Agentforce | $30~150/유저/월, CRM 종속 | $0 시작, 범용 |
| LangGraph Cloud | LangChain 종속 | 프레임워크 독립 |

**블루오션 = "개인/SMB + 돌리기(Runtime)"**

---

## 14. GTM 전략

1. **Month 1~3**: OSS 코어 공개, GitHub 스타 확보, HN/ProductHunt/GeekNews 런칭
2. **Month 4~6**: 클라우드 호스팅 베타, 무료→Pro 전환
3. **Month 7~12**: Agent Store 오픈, 크리에이터 수익 공유
4. **Year 2+**: 엔터프라이즈, Anthropic/OpenAI 파트너십

**마케팅 메시지:**
- EN: "Deploy AI agents that don't bankrupt you at 3am"
- KR: "AI 에이전트, 만들었으면 돌려야죠. 월 $0.01부터."
- HN: "Show HN: I run 6 AI agents 24/7 for $1/month. Now you can too."

**정부 지원**: 초기창업패키지 ₩1억 (즉시 지원 가능), TIPS 최대 ₩7억

---

## 15. 참고 문서

| 문서 | 위치 |
|------|------|
| 사업 리서치 보고서 | `/Users/blockmeta/Desktop/workspace/flux-openclaw/wiki/reports/agent-runtime-platform-research.html` |
| MVP 4주 로드맵 | `/Users/blockmeta/Desktop/workspace/flux-openclaw/wiki/reports/agent-runtime-mvp-roadmap.html` |
| Week 1 작업 지시서 | `./WEEK1_PLAN.md` |
| flux-openclaw CLAUDE.md | `/Users/blockmeta/Desktop/workspace/flux-openclaw/CLAUDE.md` |

---

## 16. 개발 규칙

### DO
- flux-openclaw 코어 모듈에서 추출 시 원본 구조/패턴 유지
- 보안 레이어(경로 탈출 방지, SSRF 차단, AST 스캔) 그대로 가져오기
- BYOK: 유저 API 키는 환경변수/.env로만 관리 (절대 DB 저장 안 함)
- pydantic으로 agent.yaml 엄격 검증
- 테스트 작성 (pytest)
- 한국어 + 영어 병행 (코드는 영어, 문서는 한국어 OK)

### DON'T
- 트레이딩 관련 코드 포함 금지 (flux-openclaw의 trading/ 폴더 전체 제외)
- 과도한 추상화 금지 — MVP는 심플하게
- LLM 비용을 서버에서 부담하지 않음 (BYOK)
- eval, exec, subprocess 사용 금지 (보안)

### 켈리 스타일
- **이름**: Kelly (켈리). AI를 Elon (일론)이라 부름.
- **디자인 3원칙**: (1) 필요없는 건 다 제거 (2) 레퍼런스에서 시작 (3) 목적에 따라 디자인
- **디자인 레퍼런스**: Dribbble, Awwwards, Linear, Vercel Dashboard
- 작업 완료 시 `say "켈리, 작업이 완료되었습니다"` 음성 알림
- 푸시 요청 시: CLAUDE.md 업데이트 + README 업데이트 + 커밋 + git push (4가지 한번에)
