# Flux — Week 3 작업 지시서

## 목표
CLI/runtime 위에 **웹 컨트롤 플레인**을 얹어, 다른 사람도 GitHub 계정으로 로그인해서 자기 에이전트를 만들고 굴릴 수 있게 한다. W3 끝나는 시점에 `docker-compose up` 한 줄로 풀스택이 부팅된다.

**완료 기준 (E2E):**
1. 새 유저가 GitHub OAuth로 로그인
2. 대시보드에서 "New Agent" → YAML 빌더 → 저장
3. "Run Now" 버튼으로 즉시 실행 + 진행 로그가 WebSocket으로 화면에 흘러나옴
4. 상세 페이지에서 `cost / runs / next_run_at / halt 토글` 확인
5. 두 번째 유저는 첫 유저의 에이전트를 볼 수 없음 (멀티테넌트 격리)

## 현재 상태 (W2 종료)
- CLI 14개 명령 + 데몬 + Watchdog + Safety 영속화
- 81 tests green
- `AgentRunner`가 yaml 파일 1개를 받아 실행 — **현재는 1 OS-user = 1 tenant**
- DB 없음 (모든 상태는 `~/.flux/agents/<name>/` 파일)

## W3 핵심 변경 사항 한눈에

| 레이어 | W2 상태 | W3 후 |
|---|---|---|
| 저장소 | 파일(`~/.flux`) | PostgreSQL 16 + 파일 (cost/log/heartbeat는 파일 유지) |
| 사용자 | OS 사용자 1명 | DB User + GitHub OAuth + JWT |
| 진입점 | `flux` CLI | CLI + `flux serve` (FastAPI) + Next.js 웹 |
| 격리 | `~/.flux/agents/<name>/` | `~/.flux/users/<user_id>/agents/<name>/` |
| 실행 | 포그라운드/데몬 | + 웹에서 "Run Now" 트리거 + WebSocket 진행 스트림 |

---

## 프로젝트 구조 (W3 후)

```
flux/
├── docker-compose.yml          # 신규: postgres + (optional) redis
├── pyproject.toml              # [extra=api] FastAPI/SQLAlchemy 추가
├── src/flux/
│   ├── ... (W1/W2 그대로)
│   └── api/                    # 신규
│       ├── __init__.py
│       ├── app.py              # FastAPI 앱
│       ├── deps.py             # DB session, current_user
│       ├── db.py               # SQLAlchemy async engine
│       ├── models.py           # User, Agent, Run, ApiKey
│       ├── schemas.py          # pydantic v2 request/response
│       ├── auth.py             # GitHub OAuth + JWT
│       ├── routers/
│       │   ├── agents.py       # /agents CRUD + run + halt + resume
│       │   ├── runs.py         # /agents/{id}/runs 이력
│       │   ├── auth.py         # /auth/github/login, /auth/github/callback
│       │   └── ws.py           # WebSocket: 로그/상태 스트림
│       └── services/
│           ├── runner_proxy.py # AgentRunner 인스턴스를 유저 컨텍스트로 만들어줌
│           └── log_tailer.py   # agent.log → WS 푸시
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
├── alembic.ini
└── web/                        # 신규: Next.js 14 App Router
    ├── package.json
    ├── next.config.mjs
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx              # 랜딩 (로그인 안 됐을 때)
    │   ├── (auth)/login/page.tsx
    │   ├── (app)/
    │   │   ├── layout.tsx        # 인증된 셸 (사이드바)
    │   │   ├── dashboard/page.tsx
    │   │   ├── agents/new/page.tsx
    │   │   └── agents/[id]/page.tsx
    │   └── api/auth/[...nextauth]/route.ts
    ├── components/ui/...         # shadcn/ui
    ├── lib/api.ts                # 백엔드 호출 wrapper
    └── lib/ws.ts                 # WebSocket client
```

---

## DB 스키마 (Alembic 0001)

```sql
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  github_id     BIGINT UNIQUE NOT NULL,
  github_login  VARCHAR(64) NOT NULL,
  email         VARCHAR(255),
  avatar_url    VARCHAR(512),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ
);

CREATE TABLE agents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name          VARCHAR(64) NOT NULL,         -- 유저 스코프 내 unique
  description   TEXT,
  yaml_source   TEXT NOT NULL,                 -- 원본 YAML 그대로 보관
  status        VARCHAR(16) NOT NULL DEFAULT 'idle',   -- idle/running/halted
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)
);

CREATE TABLE runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at    TIMESTAMPTZ,
  status          VARCHAR(16) NOT NULL,        -- success/error/budget_exceeded
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  cost_usd        NUMERIC(10, 6),
  tool_rounds     INTEGER,
  error           TEXT
);

CREATE INDEX runs_agent_started_idx ON runs (agent_id, started_at DESC);
```

> 비용 누적/일일 카운터는 W2의 `budget_state.json`을 그대로 사용 — DB 중복 저장 안 함.
> 단지 "이력 조회"용으로 `runs` 테이블만 추가.

---

## 인증 흐름 (GitHub OAuth)

```
[Web]                              [API]                       [GitHub]
  |                                  |                             |
  | 1. GET /login → render button    |                             |
  | 2. click → /auth/github/login    |                             |
  |--------------------------------->|                             |
  | 3. 302 redirect to GitHub        |                             |
  |<---------------------------------|                             |
  | 4. user authorizes               |---------------------------->|
  |                                  |     code                    |
  | 5. GitHub → /auth/github/callback                              |
  |                                  |<----------------------------|
  |                                  | 6. exchange code → token    |
  |                                  | 7. fetch /user              |
  |                                  | 8. upsert User in DB        |
  |                                  | 9. issue JWT (access+refresh)|
  | 10. set cookie + redirect /dash  |                             |
  |<---------------------------------|                             |
```

- **Access token**: 1시간, `HttpOnly; Secure; SameSite=Lax` 쿠키
- **Refresh token**: 30일, 별도 쿠키 + DB rotation table (선택 — MVP는 stateless JWT만)
- **시크릿**: `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` / `JWT_SECRET`은 `.env`로만
- **CSRF**: state 파라미터 검증, cookie SameSite=Lax

---

## 멀티테넌트 격리

`AgentRunner(data_dir=...)`를 그대로 활용한다 (이미 `data_dir` 옵션이 있음 — W1 코드).

- W2: `data_dir = ~/.flux/agents/<name>/`
- W3: `data_dir = ~/.flux/users/<user_id>/agents/<name>/`

`services/runner_proxy.py`가 DB의 `Agent.yaml_source`를 임시 파일로 쓰고 위 경로로 runner를 생성한다.
정해진 디렉토리 밖으로의 path traversal은 안 됨 (이미 W1 safety/scanner에서 검증).

---

## Day 15-16: FastAPI + PostgreSQL + Alembic

### docker-compose.yml
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: flux
      POSTGRES_USER: flux
      POSTGRES_PASSWORD: flux_dev
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U flux"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

### 신규 의존성
```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy[asyncio]>=2.0.30
alembic>=1.13.0
asyncpg>=0.29.0
python-jose[cryptography]>=3.3.0
httpx>=0.27.0           # 이미 있음
```

### CLI 추가
- `flux serve` — uvicorn으로 FastAPI 부팅 (개발용)

### 테스트 (목표 10개)
- DB 모델 생성/삭제/유저별 unique 제약
- repository 레이어 (agent 저장/조회)
- httpx로 `/healthz`, `/agents` (401 → 200) round-trip

---

## Day 17: OAuth + JWT + Agent API

### 라우트
| 경로 | 메서드 | 인증 | 설명 |
|---|---|---|---|
| `/healthz` | GET | X | 헬스체크 |
| `/auth/github/login` | GET | X | OAuth 시작 (state 발급) |
| `/auth/github/callback` | GET | X | 코드 교환 → JWT 발급 |
| `/auth/me` | GET | O | 현재 유저 |
| `/auth/logout` | POST | O | 쿠키 제거 |
| `/agents` | GET | O | 내 에이전트 목록 |
| `/agents` | POST | O | 생성 (yaml_source 검증) |
| `/agents/{id}` | GET/PUT/DELETE | O | CRUD |
| `/agents/{id}/run` | POST | O | 즉시 실행 (백그라운드 + run_id 반환) |
| `/agents/{id}/halt` | POST | O | emergency_stop 토글 |
| `/agents/{id}/resume` | POST | O | resume |
| `/agents/{id}/runs` | GET | O | 실행 이력 |
| `/agents/{id}/status` | GET | O | 하트비트 + 비용 요약 |

### 테스트 (목표 8개)
- OAuth state mismatch → 400
- JWT 없이 보호 라우트 → 401
- 다른 유저의 agent 접근 → 404 (정보 누설 방지)
- 잘못된 YAML 저장 → 422 (pydantic ValidationError)

---

## Day 18-19: Next.js 14 프론트엔드

### 스택
- Next.js 14 App Router + TypeScript
- TailwindCSS + **shadcn/ui** (Linear/Vercel과 동일한 톤)
- TanStack Query (백엔드 호출)
- Monaco Editor (YAML 빌더)
- next-auth 5 (GitHub provider)

### 화면

#### 1. 랜딩 `/`
- 헤로: "AI 에이전트, 만들었으면 돌려야죠"
- "Login with GitHub" 단일 CTA
- 디자인: Vercel/Linear 미니멀, 다크 모드 기본

#### 2. 대시보드 `/dashboard`
```
┌─────────────────────────────────────────────────────┐
│ Sidebar │ Agents (3)          [+ New Agent]         │
│         │                                            │
│ Agents  │ ┌─────────────────────────────────────┐   │
│ Cost    │ │ news-bot      [● running]   $0.014  │   │
│ Settings│ │ next: 2026-05-13 08:00              │   │
│         │ └─────────────────────────────────────┘   │
│         │ ┌─────────────────────────────────────┐   │
│         │ │ tweet-gen     [○ idle]      $0.003  │   │
│         │ └─────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

#### 3. 빌더 `/agents/new`
- 좌측: 폼 (name/schedule/budget/model)
- 우측: Monaco YAML 에디터 (실시간 양방향 sync)
- 하단: `Validate` (서버 검증) + `Save`

#### 4. 상세 `/agents/[id]`
```
news-bot                                [Run Now] [Halt]
─────────────────────────────────────────────────────
[Overview] [Runs] [Logs] [Config]

Last run:   2 hours ago  ✓ success  $0.014  4.2s
Next run:   in 5h 23m
Today:      $0.014 / $1.00  ▰▱▱▱▱▱▱▱▱▱
This month: $0.45  / $10.00 ▰▰▱▱▱▱▱▱▱▱

▶ Live log (WebSocket)
```

### 테스트 (목표 5개)
- Vitest로 핵심 컴포넌트 (AgentCard, BudgetBar, RunLog)
- Playwright는 W4로 미룸

---

## Day 20: WebSocket 실시간 로그/상태

### 프로토콜
- `wss://.../ws/agents/{id}?token=<jwt>` (또는 쿠키)
- 서버가 푸시:
  ```json
  {"type": "log", "ts": "...", "level": "INFO", "msg": "..."}
  {"type": "heartbeat", "ts": "...", "consecutive_failures": 0, "next_run_at": "..."}
  {"type": "run_complete", "run_id": "...", "cost_usd": 0.014, "status": "success"}
  ```
- 클라이언트가 보냄: ping/pong, subscribe topic

### 구현
- 백엔드: `services/log_tailer.py`가 `agent.log`를 `tail -f` 방식으로 읽어 큐에 푸시
- 동일 에이전트에 여러 클라이언트가 붙어도 pub/sub로 fan-out
- MVP는 in-memory pub/sub (Redis는 W4 검토)

### 테스트 (목표 3개)
- 인증 실패 시 1008 close
- 다른 유저의 agent ws 접근 차단
- log_tailer가 새 라인을 정확히 한 번씩만 푸시

---

## Day 21: 통합 검증 + 도커 컴포즈 + 문서

### E2E 검증 시나리오 (10단계)
1. `docker-compose up -d postgres`
2. `alembic upgrade head`
3. `flux serve` (8000)
4. `cd web && pnpm dev` (3000)
5. http://localhost:3000 → GitHub OAuth 로그인 (테스트 GitHub App)
6. 대시보드 → "New Agent" → 빌더 → 저장 (api 검증 + 200)
7. 상세 → "Run Now" → WebSocket으로 진행 로그 흐름 확인
8. 1회 실행 후 cost 표시 갱신 확인
9. "Halt" 토글 → 다음 실행 즉시 차단
10. 두 번째 GitHub 계정 로그인 → 첫 유저의 에이전트 보이지 않음

### docker-compose 확장
```yaml
  api:
    build: .
    command: uvicorn flux.api.app:app --host 0.0.0.0 --port 8000
    environment:
      DATABASE_URL: postgresql+asyncpg://flux:flux_dev@postgres:5432/flux
      GITHUB_CLIENT_ID: ${GITHUB_CLIENT_ID}
      GITHUB_CLIENT_SECRET: ${GITHUB_CLIENT_SECRET}
      JWT_SECRET: ${JWT_SECRET}
    depends_on: [postgres]
    ports: ["8000:8000"]
    volumes: ["~/.flux:/root/.flux"]   # 유저 데이터 디렉토리
```

### 문서
- `CLAUDE.md`: Week 3 섹션 완료 마킹
- `README.md`: "Web UI Quick Start" 섹션 추가, 스크린샷 자리 비워둠 (W4에서 실제 캡처)
- `.env.example`: `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `JWT_SECRET`, `DATABASE_URL` 추가

---

## 테스트 목표
- W2 종료 시점: 81개
- W3 종료 시점: **107개 (+26개)**
  - DB/repository: 10
  - API/인증: 8
  - 프론트 컴포넌트: 5
  - WebSocket: 3

## 새 의존성 (전체)
**백엔드 (Python):**
- fastapi, uvicorn[standard], sqlalchemy[asyncio], alembic, asyncpg, python-jose[cryptography]

**프론트엔드 (Node):**
- next 14, react 18, typescript, tailwindcss, @radix-ui (shadcn 기반)
- next-auth, @tanstack/react-query, @monaco-editor/react

---

## 위험 요소 / 사전 결정사항

| 위험 | 완화책 |
|---|---|
| GitHub App 등록/secrets 셋업이 처음이라 시간 손실 가능 | Day 17 시작 시점에 켈리가 GitHub OAuth App 1개 등록 (callback `http://localhost:8000/auth/github/callback`) |
| asyncio + APScheduler 동시 실행 충돌 | 백엔드 프로세스는 스케줄러를 띄우지 않음. 스케줄러는 별도 `flux start -d` 프로세스로 분리 유지. API는 "Run Now" 트리거만 |
| 멀티테넌트 격리 누락 | 모든 라우트에서 `Agent.user_id == current_user.id` 필터 강제. repository 레이어에서 enforce |
| Watchdog과 웹 UI 상태 동기화 | 웹은 `agent.log` + `heartbeat.json`을 읽기만 함. CLI/Watchdog이 진실의 원천 |
| Docker 미설치 환경 | `docker-compose up postgres` 안 되면 sqlite fallback (선택). MVP는 PG 필수로 가져감 |

## 참고
- W1 작업 지시서: `./WEEK1_PLAN.md`
- W2 작업 지시서: `./WEEK2_PLAN.md`
- 디자인 레퍼런스: Linear (https://linear.app), Vercel Dashboard, shadcn/ui (https://ui.shadcn.com)
- shadcn 셋업: `pnpm dlx shadcn@latest init`
