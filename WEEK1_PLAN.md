# Flux — Week 1 작업 지시서

## 목표
flux-openclaw에서 코어 모듈을 추출하여 독립 실행 가능한 에이전트 런타임 CLI 완성.
**완료 기준:** "뉴스 요약 봇" 1개를 `flux start`로 실행 성공.

## 프로젝트 정보
- **위치:** /Users/blockmeta/Desktop/workspace/flux
- **GitHub:** jeromwolf/flux
- **도메인:** flux.ai.kr
- **원본:** /Users/blockmeta/Desktop/workspace/flux-openclaw (코어 모듈 추출 원본)

## Day 1-2: 프로젝트 구조 + 코어 추출

### 프로젝트 레이아웃
```
flux/
├── pyproject.toml           # Python 패키지 설정 (pip install flux)
├── README.md                # OSS README (GIF 데모, Quick Start)
├── LICENSE                  # Apache 2.0
├── .env.example             # 환경변수 템플릿
├── src/
│   └── flux/
│       ├── __init__.py
│       ├── cli.py           # CLI 엔트리포인트 (flux init/start/stop/list)
│       ├── engine.py        # 에이전트 실행 엔진 (conversation_engine.py 추출)
│       ├── llm.py           # LLM 추상화 (llm_provider.py 추출)
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── manager.py   # 도구 관리자 (core.py ToolManager 추출)
│       │   └── builtins/    # 기본 도구 (web_search, web_fetch 등)
│       ├── safety/
│       │   ├── __init__.py
│       │   ├── shield.py    # Safety Shield (cost_tracker.py 추출 + 하드리밋)
│       │   └── scanner.py   # 도구 보안 스캔 (core.py 보안 로직 추출)
│       ├── scheduler.py     # APScheduler 기반 스케줄러
│       ├── watchdog.py      # 에이전트 헬스체크 + 자동 복구
│       ├── config.py        # 설정 관리
│       └── logging.py       # 구조화 로깅
├── agents/                  # 에이전트 정의 폴더
│   └── examples/
│       └── news-summary.yaml
├── tests/
│   └── ...
└── docs/
    └── ...
```

### flux-openclaw → flux 모듈 매핑

| flux-openclaw 원본 | flux 대상 | 수정 범위 |
|---|---|---|
| conversation_engine.py | src/flux/engine.py | 멀티테넌트 준비, 클래스 리네임 |
| llm_provider.py | src/flux/llm.py | 그대로 (이미 추상화) |
| core.py (ToolManager) | src/flux/tools/manager.py | 유저별 도구 격리 |
| core.py (보안 스캔) | src/flux/safety/scanner.py | 그대로 |
| cost_tracker.py | src/flux/safety/shield.py | 하드리밋 + Circuit Breaker 추가 |
| config.py | src/flux/config.py | agent.yaml 로딩 추가 |
| logging_config.py | src/flux/logging.py | 그대로 |

## Day 3-4: agent.yaml 포맷 + CLI

### agent.yaml 스펙
```yaml
name: news-summary-bot
description: "매일 아침 AI 뉴스를 요약해서 정리"

# 실행 설정
schedule: "0 8 * * *"        # cron: 매일 08:00
model: claude-haiku           # LLM 모델
max_tokens: 4096

# 안전 설정
budget:
  per_run: 0.10              # 실행당 최대 $0.10
  daily: 1.00                # 일일 최대 $1.00
  monthly: 10.00             # 월간 최대 $10.00

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

### CLI 명령어
```bash
flux init <name>          # agent.yaml 템플릿 생성
flux validate <file>      # agent.yaml 유효성 검증
flux start <file>         # 에이전트 실행 (포그라운드)
flux start <file> -d      # 에이전트 실행 (데몬)
flux stop <name>          # 에이전트 중지
flux list                 # 실행 중인 에이전트 목록
flux logs <name>          # 에이전트 로그 보기
flux cost <name>          # 비용 요약
```

## Day 5-7: 통합 + 테스트

### 검증 시나리오
1. `flux init news-bot` → agents/news-bot.yaml 생성
2. API 키 설정 (.env에 ANTHROPIC_API_KEY)
3. `flux validate agents/news-bot.yaml` → "Valid ✓"
4. `flux start agents/news-bot.yaml` → 뉴스 검색 + 요약 출력
5. 비용 $0.10 이내 확인
6. `flux start agents/news-bot.yaml -d` → 데몬 실행
7. `flux list` → news-bot (running, next: 08:00 KST)
8. `flux logs news-bot` → 실행 로그 확인
9. `flux cost news-bot` → "$0.003 today, $0.003 total"
10. `flux stop news-bot` → 정상 종료

### 의존성 (최소)
```
anthropic>=0.45.0
openai>=1.60.0      # 선택
httpx>=0.27.0
apscheduler>=3.10.0
click>=8.1.0        # CLI
pyyaml>=6.0
rich>=13.0          # 터미널 UI
pydantic>=2.0       # 설정 검증
```

## 참고
- 로드맵 상세: /Users/blockmeta/Desktop/workspace/flux-openclaw/wiki/reports/agent-runtime-mvp-roadmap.html
- 사업 리서치: /Users/blockmeta/Desktop/workspace/flux-openclaw/wiki/reports/agent-runtime-platform-research.html
