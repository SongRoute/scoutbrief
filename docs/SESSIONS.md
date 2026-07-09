# 세션 계획표 — 완료 조건 명령이 유일한 판정 기준

| 세션 | 담당 | 의존 | 내용 | 완료 조건 |
|---|---|---|---|---|
| S0 스캐폴딩 | 1인 단독 | — | repo 레이아웃, config.py, docs 3종, .claude/agents 3종, requirements(pybaseball==2.2.7 고정), pytest 셋업, .mcp.json 골격 | `python -c "import config; assert config.LEE_JH_ID==808982"` 통과 / `pytest --collect-only` 에러 0 / `claude agents` 목록에 3개 에이전트 표시 |
| S1 캐시 선생성 | 동일 1인 | S0 | scripts/build_cache.py — 5파일 생성(⑤ 시즌 풀은 장시간 허용), COL 불변식 assert, game_type=='R' 필터, 반올림 적용 | `python scripts/validate_cache.py` 통과 (5파일 존재 + 컬럼 스키마 일치 + ⑤ 불변식) |
| — 병렬 개시선: S1 완료 커밋 이후 A/B 동시 착수. 계약 = docs/CONTRACT.md — |
| S2 MCP 서버 | A | S1 | 4 Tool (CONTRACT §4), 캐시 우선 + source 메타, live 실패 fallback | `python scripts/smoke_mcp.py` — 4 Tool JSON에 source·rows 존재, 네트워크 차단 후 재실행에도 통과 |
| S3 Verifier | B | S1 | 층1 정규화 + 층2 POLICY_CONSTANTS + 소표본 라벨러 (CONTRACT §5) | `pytest tests/test_verifier.py` — 최소 6케이스: 정상통과/오염검출/[T3]무시/날짜무시/정책상수허용/"2스트라이크"무시. 이후 verifier-redteam으로 적대 케이스 추가 |
| S4 그래프 골격 | A 단독 | S2,S3 | graph.py 생성(이 시점 전 생성 금지), parse→fetch→synthesize→verify 선형 관통. B 모듈은 시그니처만 서브에이전트로 추출해 배선 | `python run_demo.py --linear` — 4섹션 draft 생성 |
| S5 재생성 루프 | B(노드) + A(배선) | S4 | 라우팅: retryable(=실패∧retry<MAX_RETRY)만 재생성, retryable 없고 failed 있으면 전부 escalate. 라벨 부착 | `pytest tests/test_routing.py` + `python run_demo.py --poison arsenal` 루프 로그 확인 |
| S6 HITL/LLM08 | B | S4 | interrupt, HMAC 승인 토큰, deploy 게이트 | `python run_demo.py --deploy-without-token` → PermissionError / `--approve` → out/*.md 생성 |
| S7 가드레일 | A | S4 | LLM01, LLM06(허용 우선), guard_output을 label_pass로(+deploy 잔류), RAG 더미 3건(시간 없으면 생략) | `pytest tests/test_guards.py` — "부상자 명단 복귀" 비마스킹 / "수술 부위·재활 일정" 마스킹 / 인젝션 ValueError |
| S8 통합·리허설 | 양측 | 전부 | 실리포트 생성, 시연 3장면(환각 차단/HITL 게이트/라벨링+캐시 fallback), 스크린레코딩 | 리포트 md + 녹화본 |

## 세션 킥오프 프롬프트 (공통 패턴)
docs/SESSIONS.md의 S{N}을 수행한다. CLAUDE.md, config.py, docs/CONTRACT.md를 먼저 읽어라.
완료 조건: {세션표의 실행 명령}. 이 명령이 통과할 때까지가 이번 세션의 범위 전부다.
범위 밖 리팩터링 금지. 완료 조건 통과 후 contract-reviewer로 점검하고 결과를 보고하라.

## S0 전문 (첫 세션)
ScoutBrief MVP의 S0 스캐폴딩이다. 첨부한 CLAUDE.md, docs/CONTRACT.md, docs/SESSIONS.md,
.claude/agents 3종을 그대로 배치하고, config.py를 CONTRACT.md §1 전문대로 작성하라.
requirements(pybaseball==2.2.7, langgraph, mcp, langchain-mcp-adapters, pytest), pytest 셋업,
.mcp.json 골격까지. 완료 조건: 세션표 S0 참조.
이 세션에서 src/ 아래 구현 파일을 만들지 마라. 스캐폴딩 후 전체 커밋 — 이 커밋이 병렬 개시선이다.

## 레인 온보딩 프롬프트 (병렬 개시선 이후, 각 세션 첫 메시지에 결합)

### A레인
ScoutBrief MVP의 A레인 담당이다. CLAUDE.md와 config.py, docs/CONTRACT.md를 먼저 읽어라.
담당: ① scripts/build_cache.py — CONTRACT §3 스키마 5종대로, ⑤에 COL 불변식 assert,
반올림은 여기서만. ② src/mcp_server.py — Tool 4개(CONTRACT §4), 캐시 우선 + source 메타.
get_bullpen_threats는 §4 스키마·공식대로 결정론 계산(LLM 금지), 7일 풀 전원 반환.
③ src/guards.py — CONTRACT §6. ④ S4부터 graph.py 배선 — B 노드는 import만, 로직 수정 금지.
금지: verifier.py/labels.py/hitl.py/nodes_b.py 수정, 캐시 직접 편집, config 밖 매직넘버, 사실 추측.

### B레인
ScoutBrief MVP의 B레인 담당이다. CLAUDE.md와 config.py, docs/CONTRACT.md를 먼저 읽어라.
담당: ① src/verifier.py — CONTRACT §5. 입출력 (draft, tool_results) → verify_report.
② src/labels.py — 소표본 라벨(SMALL_SAMPLE_PA), vsL_low_n 표기.
③ src/nodes_b.py — route_after_verify(수정판 라우팅), escalate(플레이스홀더 R4, 숫자 금지),
regenerate 피드백 빌더. ④ src/hitl.py — interrupt 페이로드, HMAC 토큰, deploy 게이트.
계약: 하류 실패 신호는 escalated_sections만. verify_report는 감사 로그.
금지: mcp_server.py/build_cache.py/graph.py 생성·수정, LLM 호출, config 밖 매직넘버.
테스트 우선 — 세션표의 pytest 케이스를 먼저 작성하고 구현하라. S3 완료 후 verifier-redteam 호출.

## 알려진 미결(발표 전 확인)
- 발표 당일 라이브 조회 지양 — 캐시 기본 경로. 시연 3장면 중 캐시 fallback 데모는
  네트워크 차단으로 재현.