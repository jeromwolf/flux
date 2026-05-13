# Flux — Week 4 작업 지시서

## 목표
W3 끝까지 만든 "로컬에서 도는 풀스택"을 **다른 사람이 git clone 하나로 따라할 수 있는 OSS**로 마무리하고, **Show HN으로 첫 외부 유저를 데려온다**.

**완료 기준 (E2E):**
1. 새 사용자가 `git clone` → `docker compose up postgres` → `flux serve` → `pnpm dev` → GitHub OAuth → 첫 에이전트 실행까지 10분 이내
2. README에 데모 GIF 1개 + 스크린샷 2~3장이 박혀 있다
3. `v0.1.0` 태그가 GitHub Release로 배포되어 있다
4. Show HN 포스트가 게시되어 있고 (켈리가 직접 게시), 첫 24시간 동안 댓글/이슈에 응답한다

## W4의 본질
W1~W3가 "코드 빌드"였다면 W4는 **출시 작업**이다. 비중:
- 독푸딩 + 버그 수정: 35%
- OSS 메타 정비 + 데모 자료: 25%
- 콘텐츠 작성 (Show HN/PH/GeekNews/X/Blog): 25%
- 릴리스 + 런칭 모니터링: 15%

새 코드는 최소화 — 발견된 이슈에 한해 minimal-diff로만 수정.

## 현재 상태 (W3 종료)
- 113 tests green, `863f230 feat: Week 3 완료`
- CLI 14개 명령 + Web UI 5개 화면 + 14개 API 라우트 + WebSocket
- `docker compose up -d postgres` + `flux serve` + `pnpm dev` 3 프로세스로 풀스택 동작
- 외부 노출 안 됨, GitHub OAuth App 미등록

## W4 핵심 변경 사항 한눈에

| 항목 | W3 상태 | W4 후 |
|---|---|---|
| GitHub OAuth | 미등록 | "Flux (dev)" + "Flux" 두 OAuth App 등록 (localhost / 프로덕션 미정) |
| OSS 메타 | LICENSE만 | CONTRIBUTING / CODE_OF_CONDUCT / ISSUE_TEMPLATE / PR_TEMPLATE / CI |
| README | 1500자 텍스트 | + 데모 GIF + 스크린샷 2~3장 + "10분 셋업" 섹션 |
| 예제 에이전트 | news-summary 1개 | + tweet-summary, github-trending, weather-digest (총 4개) |
| 버전 | 0.1.0 (dev) | **v0.1.0 release tag** + GitHub Release notes |
| 콘텐츠 | 없음 | Show HN / ProductHunt / GeekNews / X 스레드 / Blog post 초안 5종 |
| 비코드 디렉토리 | - | `docs/launch/` 신규 (콘텐츠 초안 보관) |

---

## Day 22-23: 독푸딩

### 시나리오 (체크리스트, 외부 유저 시각)
1. `git clone https://github.com/jeromwolf/flux`
2. `.env.example` 보고 GitHub OAuth App 1개 등록 → secrets 채움
3. `pip install -e '.[api]'` → `docker compose up -d postgres` → `alembic upgrade head`
4. `flux serve` (8000) + 새 터미널에서 `cd web && pnpm install && pnpm dev` (3000)
5. http://localhost:3000 → "Sign in with GitHub" → 콜백 → 대시보드 도착
6. "New agent" → news-bot 템플릿 → 저장 → 상세 페이지로 자동 이동
7. "Run now" → Live log 패널에 즉시 출력 흐름 (실 LLM 호출, $0.01~0.02)
8. 비용/runs/heartbeat 표시 정상
9. "Halt" → emergency_stop 파일 생김 → 다음 Run 차단 → "Resume"
10. 두 번째 GitHub 계정 로그인 → 첫 유저 에이전트 안 보임 (cross-tenant 격리)
11. CLI에서 `flux status news-bot` → 웹에서 보이는 것과 동일 (W2 호환 확인)
12. `flux start agents/news-bot.yaml -d` 데몬 + `flux watch agents/news-bot.yaml -d` 같이 → 웹이 진행 상황 반영

### 발견 가능성 높은 이슈
| 분류 | 예상 이슈 | minimal fix 위치 |
|---|---|---|
| 첫 로그인 | OAuth state 쿠키가 path=/auth 라서 dashboard 진입 시 정리 안 됨 | routers/auth.py callback에서 delete_cookie path 일치 |
| Run trigger | 동시 클릭 시 queued 행 2개 생김 | `/agents/{id}/run`에 in-progress run 체크 |
| Live log | 첫 run 시 log 파일이 없어서 tailer 무한 대기 | log_tailer FileNotFoundError 시 graceful skip (이미 처리됨, 재확인) |
| 빌더 | YAML invalid 시 에러 표시가 너무 raw | NewAgent 페이지에서 422 detail 가독성 개선 |
| 대시보드 | 로그아웃 시 캐시된 agents 리스트가 잠깐 보임 | `/auth/logout` mutation 후 queryClient.clear() |
| Watchdog 호환 | 웹에서 만든 agent를 CLI에서 `flux start <yaml>` 하려면 yaml 파일이 어디 있는지 명시 | `flux export <agent_name>` 작은 명령 추가 검토 |

이슈 발견은 **이슈 트래커 대신 코드 코멘트 + 즉시 수정**으로 처리. 외부 노출 전이라 빠른 이터레이션이 안전.

---

## Day 24: OSS 메타 정비

### 파일 추가
| 파일 | 내용 |
|---|---|
| `CONTRIBUTING.md` | dev 셋업, 테스트 실행, PR 가이드, 커밋 컨벤션, 코드 스타일(ruff) |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1 기반 |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | 재현 단계 / 환경 / 로그 위치 |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | 문제/해결책/대안 |
| `.github/ISSUE_TEMPLATE/config.yml` | discussions 링크 |
| `.github/PULL_REQUEST_TEMPLATE.md` | 변경/테스트/문서 체크리스트 |
| `.github/workflows/test.yml` | pytest + ruff + (web) tsc on push/PR |
| `.github/dependabot.yml` | weekly pip + npm 업데이트 |

### GitHub repo 설정 (jeromwolf/flux)
- Description: "Deploy AI agents that don't bankrupt you at 3am — runtime + safety + scheduling."
- Website: https://flux.ai.kr
- Topics: `ai-agents`, `llm`, `python`, `fastapi`, `nextjs`, `agent-framework`, `runtime`, `anthropic`, `openai`, `byok`
- Discussions: 활성화 (Q&A + Show and tell)
- Sponsors: 켈리 계정에 enable (있다면)
- Releases: v0.1.0이 첫 release

### LICENSE
- Apache-2.0 그대로 유지, src/flux/ 모든 새 파일에 헤더 통일 필요는 없음 (LICENSE 파일 하나로 충분)

---

## Day 25: 데모 자료

### README 자료
1. **데모 GIF**: `docs/assets/demo.gif` — 30~45초
   - `flux init` → `flux start` → 결과
   - 또는 웹 흐름(로그인 → 에이전트 생성 → Run Now → Live log) — 이게 더 인상적
   - 캡처: macOS Cleanshot X 또는 ffmpeg로 mp4 → gif 변환 (≤ 5MB)
2. **스크린샷 3장**: `docs/assets/{landing,dashboard,detail}.png`
3. README 상단에 GIF, "Features" 위에 스크린샷 3장 그리드

### 예제 에이전트 (`agents/examples/`)
- `news-summary.yaml` (이미 있음)
- `tweet-summary.yaml`: 트위터 스레드를 한 문단으로 요약 (URL 입력)
- `github-trending.yaml`: 매일 GitHub Trending Top 5 요약
- `weather-digest.yaml`: 매일 아침 날씨 + 출근 옷차림 추천

각 예제는 README "Example agents" 표에 한 줄 + 비용 추정 명시.

### CHANGELOG.md
```markdown
# Changelog
## [0.1.0] - 2026-05-13
### Added
- Week 1: Agent runtime core (engine, LLM abstraction, ToolManager, 7 builtin tools)
- Week 2: Safety Shield with disk-persisted budget state, Watchdog auto-recovery,
  hardened APScheduler (misfire_grace_time=300, max_instances=1, coalesce)
- Week 3: Web UI (Next.js 14) + Multi-tenant FastAPI API + GitHub OAuth + WebSocket
  realtime log/heartbeat/run_complete streaming
- 113 tests, Apache 2.0 license

### Notes
- BYOK: bring your own LLM API key. Flux never stores keys in the database.
```

---

## Day 26: 콘텐츠 작성

모든 콘텐츠를 `docs/launch/` 디렉토리에 초안으로 저장. 켈리가 검토 후 게시.

### 1. Show HN (`docs/launch/show-hn.md`)
- Title: `Show HN: Flux — Deploy AI agents that don't bankrupt you at 3am ($1.26/mo for 7 agents)`
- 본문 (2~3 단락):
  - "1년간 내 개인 에이전트 7개를 월 $1.26로 돌렸다"는 hook
  - 우리가 만든 것 (Safety Shield + Watchdog + Multi-tenant Web UI)
  - 왜 만들었나 ($47K 비용 폭주 + 21% 가시성)
  - 어디부터 보면 좋은가 (`flux start agents/news-bot.yaml`)
- 첫 댓글(준비): 기술 스택 + 라이센스 + BYOK 설명

### 2. ProductHunt (`docs/launch/producthunt.md`)
- Tagline: "Runtime for AI agents — safety shields, watchdog, 24/7 scheduling"
- Description: 60 words, 핵심 3 feature
- Gallery: 데모 GIF + 스크린샷 4장
- Maker comment: 켈리 톤

### 3. GeekNews (`docs/launch/geeknews.md`) — 한국어
- 제목: "Flux — AI 에이전트 24/7 운영을 위한 오픈소스 런타임"
- 본문: HN 영문 본문 한국어 의역 + 한국 개발자 관심 포인트(BYOK $0 시작)

### 4. X / Threads 스레드 (`docs/launch/x-thread.md`)
- 7 트윗 스레드, "$47,000 비용 폭주 → 우리가 만든 것" 흐름
- 마지막 트윗에 GitHub 링크

### 5. Blog post (`docs/launch/blog-running-7-agents-for-1-26.md`)
- "How I run 7 AI agents 24/7 for $1.26/mo" (1500~2000 단어)
- flux-openclaw 1년 운영 데이터 인용 (현재 포트폴리오 ₩3.5M, 누적 P&L)
- 비용 breakdown + 안전 레이어 설명
- Substack/Medium에 게시 옵션, 켈리 선택

### 톤 일관성
- 영문: "Deploy AI agents that don't bankrupt you at 3am"
- 한국어: "AI 에이전트, 만들었으면 돌려야죠. 월 $0.01부터."
- 모든 콘텐츠에 위 두 줄 중 하나가 들어가야 함

---

## Day 27: v0.1.0 릴리즈

### 체크리스트 (release_checklist.md로 별도 보관)
- [ ] `pytest -q` 113+ 그린
- [ ] `pnpm typecheck` 그린
- [ ] `docker compose --profile full up` 풀스택 부팅 확인
- [ ] README 상단 GIF/스크린샷 깨짐 없음
- [ ] `.env.example` 모든 변수 설명 됨
- [ ] `pyproject.toml` version = "0.1.0"
- [ ] `web/package.json` version = "0.1.0"
- [ ] CHANGELOG 최종 검토
- [ ] `git tag -a v0.1.0 -m "Flux v0.1.0 — first public release"`
- [ ] `git push origin v0.1.0`
- [ ] GitHub Release 생성, 본문 = CHANGELOG + Show HN 본문 일부 (assets는 비어둠)

### GitHub Release notes 형식
```markdown
# Flux v0.1.0 — first public release 🚀

**The runtime layer agents have been missing.**

[데모 GIF]

What's in 0.1.0: ... (CHANGELOG에서)

Getting started:
- CLI quick start (3 lines)
- Web UI quick start (docker compose)

[Star on GitHub] [Show HN]
```

---

## Day 28: 런칭 모니터링

### 게시 순서 (HN 알고리즘 고려)
1. 평일 오전 PT 7-9시 (한국 시간 자정-새벽 2시) 게시 — 한국 새벽에 게시 후 켈리는 잠 못 잘 각오
2. Show HN 본문 게시 → 5분 뒤 자기 첫 댓글 (기술 디테일)
3. 1시간 뒤 GeekNews 한국어 게시
4. 4-6시간 뒤 ProductHunt
5. 트위터 스레드는 HN 게시 직후

### 모니터링 (`docs/launch/metrics.md`)
| 시점 | GitHub 스타 | HN 점수 | HN 순위 | 사인업 |
|---|---|---|---|---|
| t+0h | _ | _ | _ | 0 |
| t+1h | | | | |
| t+6h | | | | |
| t+24h | | | | |
| t+48h | | | | |
| t+1w | | | | |

### 응답 가이드 (켈리 톤)
- 비판적 댓글에는 사실 + 데이터로 응답 ("you ran 7 agents for $1.26 prove it" → 포트폴리오 수치 공유)
- 기술 질문: 빠른 응답 + 코드 링크
- "this is just a wrapper" 류: 우리만의 차별점 3개(Safety/Watchdog/Multi-tenant) 명시
- 한국어 댓글에는 한국어로

### 외부 이슈/PR 응대
- 첫 이슈는 24시간 안에 라벨 + 응답
- 첫 PR은 48시간 안에 리뷰 (small이면 머지, large면 design comment)
- `good first issue` 라벨 3~5개 미리 준비

---

## 새 의존성
**Python**: 없음 (W3 그대로)
**Frontend**: 없음 (W3 그대로)
**개발 도구 (CI)**: GitHub Actions만, 별도 패키지 X

## 테스트 목표
- W3 종료 시점: 113개
- W4 종료 시점: **113~120개** (독푸딩 중 발견된 회귀 방지용으로만 추가, 적극 추가 X)

## 위험 요소

| 위험 | 완화책 |
|---|---|
| Show HN 게시 후 트래픽 spike → 단일 인스턴스로 in-memory pub/sub 한계 | "self-hosted only, no hosted demo" 명시. Hosted는 M4~6 |
| Hosted demo가 없어서 "직접 깔아야 한다"는 진입장벽 | 30초 데모 GIF로 압축. README 첫 화면에 "10분 셋업" 가이드 |
| 첫 외부 contributor의 큰 PR이 디자인을 헤침 | CONTRIBUTING에 "open an issue first for changes > 50 lines" 명시 |
| 켈리 본인 OAuth App secrets가 .env에 들어가 있는 상태로 push | `.gitignore`에 .env 확인, pre-push hook 검토 |
| 비판적 댓글에 감정 소모 | Day 28 응답 가이드 + 음성 알림 켈리 패턴 유지 |

## 참고
- W1 PLAN: `./WEEK1_PLAN.md`
- W2 PLAN: `./WEEK2_PLAN.md`
- W3 PLAN: `./WEEK3_PLAN.md`
- 디자인 레퍼런스: Linear, Vercel, shadcn/ui
- 콘텐츠 레퍼런스: tldraw show HN, supabase launch posts, ente.io launch
