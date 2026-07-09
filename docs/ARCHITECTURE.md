# ScoutBrief 아키텍처 — 유지보수·확장 가이드

작성 시점: 2026-07-10 (S8 리허설 완료 직후). 대상 독자: 이 코드베이스를 처음 여는 엔지니어.
이 문서는 "어디를 어떻게 고쳐야 하는가"를 다룬다. 무엇을 했는가는 docs/SESSIONS.md,
인터페이스 계약은 docs/CONTRACT.md, 시연 절차는 docs/DEMO.md가 이미 다룬다.
이 문서의 절 번호 인용(§1~§7)은 전부 docs/CONTRACT.md의 절이다.

---

## 1. 시스템 개요

단일 경기(COL @ SF, 2026-07-09), 단일 소비자(이정후, 좌타) 프리뷰 리포트를 자동 생성한다.
데이터는 한 방향으로 흐른다:

```
pybaseball statcast (네트워크, 빌드 타임 1회)
  → scripts/build_cache.py          반올림·필터·집계는 전부 여기서
  → cache/*.csv 5파일               읽기 전용 (§3)
  → src/mcp_server.py 4 Tool        결정론 계산(threat_score·availability) 포함 (§4)
  → src/graph.py fetch_data         tool_results = {pitcher_recent|arsenal|bvp|bullpen_threats}
  → synthesize (LLM, 섹션 4개)      유일한 비결정론 지점
  → verify (결정론, §5)             숫자 실재 대조
  → [재생성 루프 | escalate]
  → label_pass (LLM06 마스킹)
  → hitl_gate (interrupt)           ← 그래프 외부 콘솔이 HMAC 토큰 발급/미발급
  → render_deploy                   → out/brief_COL_SF_2026-07-09.md
```

### 노드 전이도 (src/graph.py `build_graph`)

```
START → parse_request → fetch_data → synthesize → [poison_draft]* → verify

verify --route_after_verify(조건 분기)-->
  "regenerate" → synthesize        # 재진입점. 실패∧retry<MAX_RETRY 섹션만 재생성,
                                   # PASS 섹션 draft 보존. synthesize 최대 1+MAX_RETRY회
  "escalate"   → escalate 노드     # retry 소진 섹션 draft를 플레이스홀더로 교체
  "done"       → (아래 모드에 따라)

with_hitl=False (--linear/--poison):
  done → END,  escalate → END     # label_pass·hitl 없음. 체크포인터 없음.

with_hitl=True (--approve/--reject/--deploy-without-token):
  done → label_pass,  escalate → label_pass      # escalate 잔존 경로도 관문을 거친다
  label_pass → hitl_gate --interrupt--> [그래프 정지]
    콘솔이 issue_approval_token 호출 → Command(resume=토큰) → render_deploy → END
    콘솔이 발급하지 않음(반려)      → 그래프는 interrupt에 영구 잔류, 배포 없음
  # MemorySaver 체크포인터로 컴파일 — interrupt 재개의 전제
```

`[poison_draft]*`는 `run_demo.py --poison`이 주입하는 데모 계측 노드로, 운영 경로에는 없다.

### 실행 표면

`run_demo.py`의 5개 플래그(--linear/--poison/--deploy-without-token/--approve/--reject)와
`scripts/` 3종(build_cache/validate_cache/smoke_mcp). 전체 목록과 기대 출력은 DEMO.md 부록.

### 신뢰 모델 요약

숫자의 **실재**는 기계(§5 verifier)가, 숫자의 **의미**(해석 방향·표본 귀속)는 사람(§6 HITL)이
보증한다. 이 분업은 §5에 명문화된 설계이며, 4절의 결함 다수가 이 경계선 위에 있다.

---

## 2. 파일별 책임과 결합도

원칙: "무엇에 의존하는가"가 아니라 "바꾸면 어디서 터지는가"를 쓴다.

### config.py — §1과 문자 단위 일치가 계약

한 글자라도 바꾸면 contract-reviewer가 FAIL을 낸다(§1 "이 내용이 곧 스펙"). 그 전에
코드에서 터지는 곳:

| 바꾸는 것 | 터지는 곳 |
|---|---|
| `SECTION_KEYS` | `src/graph.py`의 `assert set(SECTION_SPECS) == set(config.SECTION_KEYS)` 즉사. `SECTION_SPECS`에 대응 항목이 없으면 synthesize에서 KeyError. `tests/test_routing.py`의 `CLEAN` 픽스처(명시적 dict) KeyError. |
| `POLICY_CONSTANTS` | verifier 층2 판정이 즉시 바뀐다. 원소 제거 시 그 문자열을 쓰는 draft가 전부 FAIL로 전환 — `test_policy_constant_allowed`("20"), `test_redteam_undefined_footnote_T5...`("5") 등이 뒤집힌다. 원소 추가는 그 숫자의 날조를 전면 허용하는 것과 같다(4절 첫 결함 참조). |
| `MAX_RETRY` | 루프 상한. `test_retry_exhaustion_escalates_and_terminates`가 `1+MAX_RETRY`회 생성을 고정하고 있다. 값 "2"는 POLICY_CONSTANTS에도 들어 있으므로 함께 바꾸지 않으면 화이트리스트와 어긋난다. |
| `SMALL_SAMPLE_PA` | `labels.small_sample_banner` 임계 + 화이트리스트의 "20". 배너 문면의 PA 수치는 tool_results에 실재하는 값(pa_total)이라 verifier와는 무관. |
| `GAME_DATE_US` | Tool 4 `rest_days` 계산 기준, `hitl.OUT_FILENAME`, `run_demo.DEFAULT_REQUEST`. 캐시 재생성 없이 바꾸면 rest_days가 캐시 창과 어긋난 값으로 계산된다. |
| `CACHE_END` | 모든 Tool의 `source` 문자열, `validate_cache`의 7일 창·기간 불변식, `build_cache` 조회 종료일. 바꾸고 캐시를 재생성하지 않으면 validate_cache FAIL. |
| `availability()` 본문 | Tool 4의 availability·threat_score 전부. smoke_mcp의 내림차순 assert는 통과할 수 있어도 순위가 조용히 바뀐다 — 배포본 순위표와 ⚑ 전략의 전제가 무효화된다. |

### src/verifier.py — §5의 구현. 층1 패턴은 계약 문면과 대응

`verify_report(draft, tool_results)` 시그니처는 `src/graph.py verify` 노드가 배선한다.
고치면 터지는 곳:

- **층1 `_STRIP_PATTERNS`를 조이면** `tests/test_verifier.py`의 레드팀 4건이 뒤집힌다 —
  `test_redteam_double_digit_suffix_ball_leaks_prefix`, `..._inning_leaks_prefix`,
  `..._source_meta_date_token_leaks_into_corpus`, `..._undefined_footnote_T5...`는
  **현재의 버그 동작(통과)을 assert로 문서화**해 둔 테스트다. 층1을 고치는 세션은 이
  4건을 의도적으로 반전시켜야 하며, 이는 §5 개정과 함께 가야 한다(계약이 층1 패턴을
  전문으로 명시).
- **corpus 구성(`_tool_results_numbers`)을 바꾸면** — 예: data 필드로 제한 — §5에 명문화된
  개정 세션 결론(false-fail만 늘고 이 클래스를 못 잡음)과 충돌한다. 개정 없이 코드만
  바꾸면 contract-reviewer FAIL.
- verifier는 **원본 tool_results**를 받는 것이 전제다(`_llm_view` 개명본이 아니라).
  graph.py의 `LLM_VIEW_RENAMES` 주석("★ verifier에는 반드시 원본")이 이 결합을 지킨다 —
  실수로 뷰를 넘기면 `pitches`로 개명된 키 때문이 아니라(키 이름은 숫자가 아니다)
  동작은 같아 보이지만, 진실 공급원이 둘로 갈라져 이후 뷰 확장 시 조용히 어긋난다.

### src/mcp_server.py — §4의 구현. Tool 4 반환 스키마를 바꾸면 연쇄되는 것

Tool 4(`get_bullpen_threats`)의 행 필드를 추가·개명·삭제하면:

1. `scripts/smoke_mcp.py`의 `TOOL4_FIELDS` 튜플(15개 필드명 하드코딩) — 삭제·개명 시 즉사.
2. `src/graph.py SECTION_SPECS`의 bullpen·gameplan 지시문 — 필드명이 산문으로 박혀 있다
   (`vsL_top2_usage`, `vsL_low_n`, `bvp_pa`, `bvp_xwoba`, `rest_days`, `appearances_7d`,
   `pitches_7d`, `last_game`, `lefty_flag`). LLM이 없는 필드를 지시받으면 날조하거나 누락한다.
3. **verifier corpus** — tool_results 직렬화 전체가 corpus이므로 숫자 필드 추가는
   화이트리스트를 사실상 넓힌다. 예컨대 순위(1~N)를 필드로 추가하면 1~7의 모든 한 자리
   정수가 corpus에 실리며, draft의 근거 없는 한 자리 수가 통과할 표면이 넓어진다
   (6절 §4-A 안건의 역효과 항목).
4. docs/CONTRACT.md §4 행 스키마 표 — 계약 개정 없이는 contract-reviewer FAIL.
5. `hitl.build_interrupt_payload`가 tool_results 원본을 분석관 화면에 그대로 싣는다 —
   스키마 변경은 분석관이 대조하는 화면의 변경이다.

Tool 1~3의 캐시 가드(`pitcher_id != config.FELTNER_ID`류 ValueError)는 캐시가 단일
선수·단일 매치업 전용임을 강제한다 — 5절 확장 시나리오의 출발점.

### scripts/build_cache.py — 반올림·필터·집계의 유일한 장소

`fetch_season_raw`의 COL 불변식 assert는 pybaseball 버전 드리프트 감지선(§3 ⑤, 제거 금지).
`build_*` 4개 함수는 live 경로(`SCOUTBRIEF_LIVE=1`)에서 mcp_server가 재사용한다 —
여기 로직을 바꾸면 캐시 경로와 live 경로가 함께 바뀐다(단일 출처, 의도된 결합).
집계 규약을 바꾸면 `scripts/validate_cache.py`의 스키마·불변식(usage_pct 합 100,
7일 창, 반복 컬럼 동일성)이 감지한다.

### src/graph.py — 배선 + LLM 프롬프트 + 결정론 후처리 (A레인)

`SYSTEM_PROMPT`와 `SECTION_SPECS`는 이 시스템에서 가장 자주 고쳐졌고 가장 효과가
불확실했던 부분이다(4절 bullpen 결함 참조). 여기의 결정론 후처리 — matchup 배너 부착,
gameplan `NO_FORWARD_NOTICE` 부착 — 는 재생성 경로에서도 재부착된다(synthesize 내부).
`label_pass`는 함수 소스에 `verify_report` 문자열이 없어야 한다 —
`test_label_pass_does_not_read_verify_report`가 `inspect.getsource`로 정적 검사한다.

### src/nodes_b.py — 라우팅·escalate (B레인)

`split_failed`가 (retryable, exhausted) 분류의 단일 공급원이고, `route_after_verify`와
`escalate`, graph.py의 synthesize 재생성 대상 선정이 전부 이 함수를 공유한다.
`ESCALATE_PLACEHOLDER`와 `_REGEN_FEEDBACK`에 숫자를 넣으면
`test_regen_feedback_contains_no_digits`/`test_escalate_placeholder_contains_no_digits`가
잡는다(R4 + 정답 주입 금지).

### src/hitl.py — 토큰·관문·배포 (B레인)

`deploy_markdown`이 approve-what-you-see의 핵심이다: hitl_gate(검증)·render_deploy(기록)·
콘솔(발급)이 **같은 함수로 재합성한 바이트**에 서명·검증한다. 이 함수의 출력을 1바이트라도
바꾸면(공백·개행 포함) 발급-검증 사이에 낀 모든 토큰이 무효가 된다. `guards.guard_output`의
문장 분리가 캡처 그룹으로 공백을 보존하는 이유도 이것이다(guards.py `_SENTENCE_SEP` 주석).
`issue_approval_token` 호출이 hitl_gate/render_deploy/graph.py 소스에 나타나면
`test_llm08_nodes_do_not_issue`가 정적 검사로 잡는다.

### src/guards.py — LLM01/06 (A레인)

`INJECTION_PATTERNS` 6종과 `MASK_TOKEN` 문면은 §6과 문자 단위 일치가 계약이다.
패턴을 고치면 CONTRACT.md §6도 함께 개정해야 한다. `MASK_TOKEN`을 바꿀 때는 모듈 로드
assert(ALLOW/BLOCK 비매치)와 "문장 종결부호 없음" 조건을 지켜야 멱등성이 유지된다 —
깨지면 `test_guard_output_idempotent`가 잡고, 실전에서는 render_deploy의 2차 적용이
label_pass 결과를 재변형해 승인 해시가 깨진다(승인한 문서와 배포 문서가 달라짐).

### src/llm.py — 유일한 LLM 접점

`chat(system, user)` 하나. 모델명은 env `SCOUTBRIEF_LLM_MODEL`(기본 gpt-4o-mini),
temperature 0.2. §1 명문으로 계약 대상이 아니다 — 여기만 고치면 계약 개정 없이 모델이
바뀐다. 단, 5절 시나리오 5의 주의사항(프롬프트 방어의 모델 종속성)을 보라.

### tests/ 54건 — 어느 테스트가 어느 불변식을 고정하는가

| 파일 (건수) | 고정하는 불변식 |
|---|---|
| test_verifier.py (20) | §5 층1 소거 6패턴·층2 화이트리스트·corpus 대조. 이 중 4건은 **알려진 우회의 버그 문서화**(통과를 assert) — 층1 수정 시 의도적으로 반전해야 한다. 나머지 레드팀 4건은 토큰 단위 대조가 부분 문자열 일치를 차단함을 고정. |
| test_routing.py (11) | S5 라우팅 3분기, retryable/exhausted 분류 순서, escalate의 draft 교체·R4 무숫자, 재생성 피드백 무숫자(정답 주입 금지), 실패 섹션만 재생성(선택성), `1+MAX_RETRY` 구조적 종료, poison 노드의 1차 한정 주입. |
| test_guards.py (7) | LLM06 허용 우선·문장 단위·마스킹 문면, guard_output 멱등, render_deploy 이중방어(label_pass 우회 오염도 배포본은 마스킹), LLM01 ValueError, label_pass의 R1 정적 검사. |
| test_hitl.py (9) | HMAC 왕복·위조·변조·빈 토큰 거부, 키 미설정 PermissionError, 미승인 배포 PermissionError, 승인 배포 기록, 페이로드의 verify_report 배제(R1), 노드 미발급 정적 검사(LLM08). |
| test_arsenal_split.py (5) | §3 ② runners_group 축(p3 신설): ON/EMPTY 마스킹 규칙, build_arsenal 축 규약·컬럼, usage_pct 셀그룹 합 100, Tool 2 행의 runners_group 오프라인 반환, feltner 지시문의 주자 스플릿 문면(해석 금지 포함). |
| test_approve_gate.py (2) | --approve 판단 지점(p1 신설, 4.5 해소 이력): y 외 입력 시 토큰 미발급·배포 없음, y 입력 시 발급·재개·배포. |

시사점: **verifier의 의미론과 프롬프트의 품질은 테스트가 지키지 않는다.** 54건 어디에도
"LLM이 방향을 옳게 서술하는가"를 고정하는 테스트는 없다 — 비결정론이라 pytest로 고정할
수 없고(CLAUDE.md 규칙 11의 판정 주체 원칙), 이것이 4절 bullpen 결함이 5회 실행 중
4회 관측되고도 회귀 테스트가 없는 이유다.

---

## 3. 설계 결정과 그 이유

각 항목: 결정 / 이유 / 버린 대안과 그 이유.

### 3.1 §5 verifier는 숫자의 '실재'만 본다

**결정**: draft의 숫자 토큰이 tool_results 직렬화(corpus) 또는 POLICY_CONSTANTS에
존재하는지만 검사한다. 해석 방향·표본 귀속·단위는 보지 않는다.

**이유**: 검증기가 결정론이어야 한다는 규칙(CLAUDE.md 규칙 4)이 상위 제약이다. 의미
검증의 두 경로가 모두 이 제약이나 오탐과 충돌했다.

**버린 대안**:
- *LLM 판정자(draft를 다른 LLM이 채점)* — 규칙 4 위반. 검증기 자체가 환각 가능해지고,
  "검증 실패"가 재현 불가능해져 재생성 루프의 종료 조건이 비결정이 된다.
- *단위·문맥 파싱(층2에 "숫자+단위" 도입)* — 한국어 단위 표현(타수/안타/구/마일/PA/%/개…)의
  열거가 닫히지 않아 false-fail이 실보다 크다고 판단, MVP 범위에서 보류. 단 이 판단은
  "20타수 8안타"가 배포본을 통과한 지금 재평가 대상이다(4절 첫 결함, 6절 §5-A).
- *corpus를 data 필드로 제한* — 2026-07-10 개정 세션에서 검토 후 기각. zone·pitches·PA 등
  data 내부의 1~2자리 수가 그대로 남아 이 클래스를 못 잡고 false-fail만 는다(§5 명문).

의미 오류의 방어선은 §6 HITL(분석관 반려)로 지정됐다. 이 분업 자체가 계약 문면이다.

### 3.2 LLM 전용 뷰(`_llm_view`)를 만들고, verifier에는 원본을 넘긴다

**결정**: arsenal·bvp의 `n` 컬럼을 프롬프트에서만 `pitches`로 개명한다
(graph.py `LLM_VIEW_RENAMES`). verifier는 원본 tool_results로 대조한다.

**이유**: `n`이 자기설명적이지 않아 LLM이 타수로 오독하는 사고가 실제로 났다
(S4 직후 synthesize 의미 오류 수정). 캐시 스키마(§3)와 Tool 반환(§4)은 동결이므로
원천을 고칠 수 없고, 프롬프트 직전의 파생 뷰가 유일하게 계약을 건드리지 않는 지점이다.

**버린 대안**:
- *캐시/Tool에서 컬럼 개명* — §3·§4 개정 + 캐시 재생성 + 양 레인 코드 수정. 개명 파급이
  검증·스모크·문서 전체에 미친다. 오독 방지라는 목적 대비 과대 수술.
- *verifier에도 뷰를 넘김* — 진실 공급원이 갈라진다. 뷰는 "LLM 입력"이고 corpus는
  "Tool이 실제 반환한 것"이어야, 뷰 가공 로직의 버그가 검증을 오염시키지 않는다.
  키 이름만 바뀌는 지금은 결과가 같지만, 뷰가 행 필터링·요약으로 확장되는 순간
  corpus가 좁아져 정당한 인용이 FAIL 나거나 그 반대가 된다.

### 3.3 `label_pass`가 `hitl_gate` 앞이다

**결정**: LLM06 마스킹을 분석관 관문 **앞**에 둔다.

**이유**: approve-what-you-see. 분석관이 승인하는 바이트열과 배포되는 바이트열이 같아야
HMAC 해시 바인딩이 의미를 가진다. 마스킹이 승인 뒤에 일어나면 승인한 문서와 배포
문서가 달라 (a) 해시가 깨져 배포가 불가능하거나 (b) 해시를 마스킹 후 재계산해야 하는데
그러면 분석관은 자기가 못 본 문서를 승인한 셈이 된다.

**버린 대안**: *render_deploy에서만 마스킹* — 위 (a)/(b) 딜레마. 현재 render_deploy의
guard_output은 마스킹의 주체가 아니라 이중방어이며, 멱등성 덕분에 정상 경로에서
no-op이라 해시를 깨지 않는다(3.4).

### 3.4 `guard_output`이 두 곳에 있다 (label_pass 끝 + render_deploy 내부)

**결정**: 같은 필터를 두 번 배치하고, §6에 "제거 금지"를 명문화했다.

**이유**: label_pass는 그래프 배선상의 보장일 뿐이다. 체크포인터 상태 조작, 배선 실수,
향후 리팩터링으로 label_pass를 우회한 draft가 render_deploy에 도달하는 경로를 코드
수준에서 막을 수 없다. render_deploy 내부 적용은 "배포되는 것은 반드시 마스킹을
통과했다"를 배선과 무관하게 보장한다. `test_double_defense_in_render_deploy`가 이
우회 시나리오를 직접 재현한다. 비용이 없는 이유는 멱등성이다: 정상 경로에서 2차 적용은
바이트 동일(no-op)이라 승인 해시가 유지된다. 멱등 조건(MASK_TOKEN이 ALLOW/BLOCK
비매치·종결부호 없음)은 guards.py 모듈 로드 assert가 지킨다.

**버린 대안**: *한 곳만* — label_pass만이면 우회 시 의료 상세가 배포되고, render_deploy만이면
분석관이 마스킹 전 문서를 승인한다(3.3의 딜레마).

### 3.5 `issue_approval_token`은 그래프 외부에서만 호출된다

**결정**: 발급 함수는 존재하되, 그래프 노드·배선 소스에서 호출되지 않는다.
`run_demo.py`(콘솔)가 유일한 호출자이고, `test_llm08_nodes_do_not_issue`가 정적으로 지킨다.

**이유**: LLM08의 요체는 "승인 권한이 파이프라인 밖에 있다"이다. 그래프가 스스로 토큰을
발급할 수 있으면 hitl_gate는 형식적 통과 의례가 된다 — LLM 출력이나 상태 오염이 승인을
유도할 수 있는 어떤 경로도 남기지 않는다.

**버린 대안**: *hitl_gate가 조건 충족 시(예: escalated_sections 비어 있음) 자동 승인* —
"자동 검증 전부 통과 + 사실 오류"가 실제로 관측되는 시스템(4절)에서 자동 승인은
HITL의 존재 이유를 소거한다. 한때 `--approve` 데모가 사실상 이 대안을 재현하고
있었다(4.5 — 2026-07-10 입력 분기 추가로 해소).

### 3.6 반려는 "토큰 미발급"이다 — 그래프에 반려 분기가 없다

**결정**: hitl_gate 이후 승인/반려 조건 분기를 만들지 않았다. 반려 = 콘솔이 발급하지
않는 것. 그래프는 interrupt에 잔류하고, 배포 산출물은 생성되지 않는다(§6).

**이유**: 안전한 상태가 기본값(부작위)이어야 한다. 반려를 그래프의 능동 분기로 만들면
(a) "반려 처리" 코드 경로가 또 하나의 버그 표면이 되고, (b) 그 분기로 진입 '시켜야만'
안전해지는 fail-open 구조가 된다. 미발급 방식에서는 아무것도 하지 않으면 아무것도
배포되지 않는다 — 우회할 코드 경로 자체가 없다. PermissionError는 반려가 아니라
무효·부재 토큰으로 배포를 '시도'한 경우의 방어라는 구분도 §6에 명문화됐다.

**버린 대안**: *reject 분기 + 상태 플래그* — 위 fail-open 위험에 더해, 반려 후 동작
(재생성? 수정? 폐기?)의 정의가 필요해지는데 그것은 MVP 범위 밖의 워크플로 설계다.
현행 구조는 "반려 이후는 엔지니어의 일"로 경계를 긋는다(DEMO.md 장면 2-3).

### 3.7 재시도 카운터가 섹션별이다

**결정**: `retry_counts`는 SECTION_KEYS별 dict이고, 재생성은 실패 섹션만 대상이다
(synthesize의 targets 선정 + PASS 섹션 draft 보존).

**이유**: 실패 격리. 전역 카운터거나 전 섹션 재생성이면 (a) 멀쩡한 섹션을 다시 생성해
비용을 쓰고 **통과했던 섹션에 새 오류를 유입**시킬 수 있으며(LLM 재생성은 매번 다른
출력), (b) 한 섹션의 반복 실패가 다른 섹션의 재시도 예산을 소모한다. 섹션별 카운터는
synthesize 실행 횟수에 구조적 상한(`1+MAX_RETRY`)을 주어 무한루프를 배선 수준에서
차단한다 — `test_retry_exhaustion_escalates_and_terminates`가 이 상한을 고정한다.

**버린 대안**: *전역 카운터* — 위 (a)(b). *무제한 재시도 + 시간 제한* — 비결정론적 종료,
데모·테스트 불가.

### 3.8 `guard_output`이 `--linear` 경로에 없다

**결정**: label_pass와 render_deploy는 `with_hitl=True` 그래프에만 배선된다.
`--linear`/`--poison`의 콘솔 draft는 마스킹되지 않는다. §6에 명문화("이 배치는 with_hitl
경로 한정 — 개발 데모는 배포 산출물이 없어 guard_output 대상이 아니다").

**이유**: LLM06의 보호 대상은 **배포 산출물**이다. --linear는 배포물이 없는 개발·시연
경로이고, 여기서 마스킹하면 개발 중 LLM 원출력을 관찰할 수 없어 마스킹 자체의 디버깅이
어려워진다(마스킹 전 문장이 무엇이었는지 봐야 ALLOW/BLOCK 패턴을 조정할 수 있다).

**버린 대안**: *전 경로 마스킹* — 위 관찰성 손실. **수용된 결과**: --linear 콘솔 출력에는
의료 상세가 노출될 수 있다. --linear 출력을 스크린샷·복사해 외부 공유하면 LLM06 방어를
우회한 유출이 된다 — 이 경계는 코드가 아니라 운영 규율이 지킨다.

### 3.9 (보조) source 메타가 mtime이 아니라 CACHE_END인 이유

Tool의 `source` 문자열에 파일 mtime을 쓰면 clone/checkout마다 값이 바뀌어 재현성이
깨질 뿐 아니라, **비결정 숫자 토큰이 verifier corpus에 유입**된다(mcp_server.py 헤더 주석).
corpus는 화이트리스트를 겸하므로 corpus의 모든 숫자는 통제된 상수여야 한다 — 이 결정은
`test_redteam_source_meta_date_token_leaks_into_corpus`(임의 타임스탬프를 넣으면 실제로
우회가 생김을 문서화)의 근거이기도 하다.

---

## 4. 알려진 결함

자기 작업의 결함 목록이다. 관대하게 평가하지 않았다. 각 항목: 증상 / 근본 원인 /
왜 안 고쳤는가 / 고치려면.

### 4.1 `POLICY_CONSTANTS` 문맥 무시 — "20타수 8안타" 날조가 배포본을 통과했다

- **증상**: 배포본 `out/brief_COL_SF_2026-07-09.md` matchup 섹션에 "이정후의 전체 통산
  성적은 20타수 8안타이다"가 실렸다. 캐시 ③의 실측은 5타수 2안타(ab_total=5,
  hits_total=2)다. §5는 PASS를 냈고, HITL 승인(--approve)까지 통과해 배포됐다 —
  **정책 상수 화이트리스트 경유 날조가 배포본에 출현한 첫 실물**이다.
- **근본 원인**: `POLICY_CONSTANTS = {"20","7","5","2","30"}`은 각각 `SMALL_SAMPLE_PA`,
  `BULLPEN_DAYS`, `RECENT_GAMES`, `MAX_RETRY`, `VSL_LOW_N_PITCHES`의 문자열 표현인데,
  층2 대조는 **문자열 집합 멤버십**이라 단위·문맥을 보지 않는다. "20타수"의 "20"은
  소표본 기준(PA)으로서 화이트리스트에 있는 것이지 타수가 아니다. "8"은 corpus 우연
  일치(zone 8 등 data 내부 한 자리 수)로 통과했다. 특히 **`MAX_RETRY=2` — 재생성 루프
  상한이라는, 야구 기록과 아무 관련 없는 정책 상수 — 가 "2안타"류의 모든 날조를
  뚫는다**: "X타수 2안타"는 X가 화이트리스트나 corpus에 있는 한 항상 PASS다.
- **왜 안 고쳤는가**: 층2 설계 시점(S3)에는 정책 상수를 본문에 인용할 정당한 수요
  ("기준 20 PA 미만")가 있었고, 문맥 인지의 비용(한국어 단위 열거)이 크다고 판단했다.
  배포본 실물은 S8 리허설에서야 관측됐다.
- **추가 근거 (2026-07-10)**: P4 모델 비교 --linear #2(gpt-4o-mini)에서 "통산 20타수
  8안타"가 동일 클래스로 재발했다(logs/runs.md). 배포본 1회의 우연이 아니라
  재현되는 클래스다 — 같은 두 토큰("20" 화이트리스트 + "8" corpus 우연 일치)이
  같은 문형으로 통과했다.
- **고치려면**: 6절 §5-A(숫자+단위 문맥 인지)가 최소 수선, §5-C(필드 인지 대조)가
  근본 해법. 둘 다 §5 개정 필요. 즉효 완화책: 정책 상수의 본문 인용을 금지하고(§7 개정 +
  프롬프트) 화이트리스트를 비우는 방안이 있으나, 소표본 배너 등 결정론 부착 문구의
  "20"이 FAIL 나므로 층1에 배너 문면 소거를 추가해야 한다.

### 4.2 bullpen ⚑ 전략의 방향 반전 — 5회 실행 중 4회, 프롬프트 방어 2차 실패

- **증상**: bullpen 섹션 하단 ⚑ 전략 문단이 위 순위표와 반대로 말한다. 두 패턴:
  (a) vsL xwOBA **값을 직접 해석**하며 방향을 뒤집는다(예: 최고 xwOBA=가장 공략하기
  좋은 Mejia를 "까다로운 상대"로). (b) **순위 의미 자체를 반전**한다(예: 위협 1위
  Vodnik을 "위협 점수가 가장 높아 적극 공략해야"로). 누적 5회 실행 중 4회 관측.
- **근본 원인**: xwOBA는 타자 관점 지표(높을수록 타자 유리)인데, "투수의 vsL xwOBA가
  낮다=좌타 억제=위협"이라는 2단 반전을 LLM(gpt-4o-mini)이 일관되게 유지하지 못한다.
  §5는 숫자 실재만 보므로 원리상 못 잡는다(값 자체는 전부 실재).
- **왜 안 고쳤는가**: 고치려 했고 **두 번 실패했다**. 1차: SYSTEM_PROMPT 규칙 9(해석
  방향 명문화 + 금지 예시) 강화 — 재발. 2차: bullpen 지시문을 "값 해석 금지, 순위만
  근거로"로 교체 — 3회 중 2회 재발(패턴 b가 이때 출현: 값 해석을 막자 순위 의미를
  반전). 프롬프트 계층에서 이 클래스를 소거할 수 없다는 것이 현재까지의 실증이고,
  방어선은 HITL 반려뿐이다(DEMO.md 장면 2가 이를 시연 소재로 쓴다).
- **모델 교체도 실패했다 (2026-07-10 P4 실측, logs/runs.md)**: --linear 5회×2모델
  비교에서 방향 반전 합계(bullpen-a + bullpen-b + bvp-반전)는 gpt-4o-mini 13건/5회,
  gpt-5.4-mini **14건/5회** — 상위 모델이 이 클래스를 줄이지 못하고 오히려 늘렸다
  (bvp-반전 4→6, bullpen-a 7→8; bullpen-b만 2→0). 프롬프트 방어에 이어 모델 계층의
  해법도 기각된 셈으로, 코드 측 해법(§7-A 템플릿화)의 근거가 하나 더 쌓였다.
- **고치려면**: ⚑ 전략 문장을 LLM에서 회수해 결정론 템플릿으로 생성(6절 §7-A).
  순위표는 이미 결정론 데이터이므로 "상위 K명은 주의, 하위는 공략 여지" 같은 문장은
  코드가 쓸 수 있다. §7 개정 필요(⚑의 '추정' 지위 재정의).

### 4.3 matchup 통산 성적 반복 — 통산값이 구종별 전적처럼 붙는다

- **증상**: 배포본 matchup의 구종별 목록 4행 각각에 "5타수 2안타"가 반복된다
  ("체인지업 (CH): 5타수 2안타 (투구수: 2, …)" 식). 5타수 2안타는 전 구종 합산
  통산인데 구종별 전적으로 읽히는 표본 귀속 오류다.
- **근본 원인**: 캐시 ③ 스키마 자체가 반정규화다 — `ab_total`/`hits_total`이 §3 명문으로
  "전 행 동일값 반복" 컬럼이라, LLM에 전달되는 JSON의 **모든 구종 행에** 통산값이 붙어
  있다. 프롬프트는 "통산은 X타수 Y안타 형식"만 지시했지 "1회만, 구종 행에 붙이지 마라"를
  지시하지 않았다.
- **왜 안 고쳤는가**: 숫자 자체는 실재값이라 §5 통과가 정당하고(날조 아님), 4.1·4.2보다
  피해가 작다고 보아 우선순위에서 밀렸다. §3 스키마는 동결이라 캐시 쪽 수선은 계약
  개정 사안이었다.
- **고치려면**: 계약 개정 없이 가능한 경로가 있다 — `_llm_view`에서 bvp의 반복 컬럼을
  행에서 떼어 별도 요약 객체(`{"totals": {...}, "by_pitch": [...]}`)로 재구성한다
  (뷰 계층 선례 있음, verifier는 원본 대조라 무영향). 보조로 matchup 지시문에
  "통산은 마지막에 1회만" 명시.

### 4.4 `bvp_xwoba` 귀속 반전 — 0.895를 "주의 필요"로 서술

- **증상**: 배포본 gameplan: "로마노는 bvp_xwoba가 0.895로 매우 높아 주의가 필요하다",
  "bvp_xwoba가 높은 투수와의 대결을 피하는 것이 좋다". `bvp_xwoba`는 **이정후가 그
  투수에게 기록한** 생산성이다 — 0.895(1 PA이긴 하나)는 이정후가 잘 쳤다는 뜻이고,
  올바른 서술은 그 반대다.
- **근본 원인**: 4.2와 같은 클래스(귀속·방향 반전)의 gameplan 변종. gameplan 지시문은
  null-BVP 날조와 vsL/bvp 혼동은 막았지만("bvp_xwoba가 null인 투수를 BVP 근거로 서술
  금지" 등), bvp_xwoba의 귀속 주체(타자 기록)까지는 명시하지 않았다. SYSTEM_PROMPT
  규칙 9는 "투수 기록의 xwOBA"를 다루는데 bvp는 타자 관점 개인 전적이라 규칙의 문면이
  정확히 덮지 못한다.
- **왜 안 고쳤는가**: S8 리허설 배포본에서 관측된 최신 결함으로, 4.2의 프롬프트 방어
  2차 실패 이후 같은 계층의 3차 수정은 효과 불확실로 보류했다.
- **안정적 실패 모드로 승격 (2026-07-10)**: 같은 값의 같은 반전 — Romano bvp_xwoba
  0.895를 "주의/까다로움"으로 — 이 S8 배포본, P4 --linear #5(gpt-4o-mini), P5 배포본
  (--approve)에서 **3회 관측**됐다(logs/runs.md). 산발 사례가 아니라 이 데이터·프롬프트
  조합에서 재현되는 실패 모드다. 모델 계층도 답이 아니라는 실측(4.2의 P4 항목 —
  gpt-5.4-mini에서 bvp-반전 4→6건)까지 겹쳐, 방어선은 여전히 HITL 반려뿐이다.
- **고치려면**: 단기 — gameplan 지시문에 "bvp_xwoba는 이정후가 기록한 값, 높을수록
  이정후가 강했음" 1행 추가(코드만, 다만 4.2 전례상 성공 보장 없음). 소표본(bvp_pa 1)
  수치의 강한 해석 금지 지시는 이미 있으나 무시됐다. 구조적 해법은 4.2와 동일하게
  결정론 템플릿화 또는 HITL 의존.

### 4.5 [해소됨 2026-07-10] `--approve`가 자동 승인이었다 — 분석관 판단 지점이 없었다

- **증상**: `run_demo.py run_approve()`는 분석관 검토 화면을 **출력한 직후** 무조건
  `issue_approval_token`을 호출한다. 사람이 읽고 판단하는 시점이 없다 — "20타수 8안타"
  배포본(4.1)이 승인·배포된 직접 경로가 이것이다. HITL의 시연 표면이 HITL을 형해화한다.
- **근본 원인**: S6의 완료 조건이 "`--approve` → out/*.md 생성"이라 자동화된 해피패스로
  구현됐고, 반려는 별도 플래그(--reject)로 분리됐다. 승인/반려가 **실행 전에 결정**되는
  구조여서, 화면을 보고 결정하는 본래의 HITL 흐름이 데모 표면에 없다.
- **왜 안 고쳤는가**: 시연 각본(DEMO.md)이 장면을 분리 설계(2-3은 --reject, 배포는
  --approve)해서 각본상으로는 문제가 드러나지 않았고, 개정 세션의 반려 경로 신설이
  --reject 추가에서 멈췄다.
- **고치려면(원문)**: `run_approve`에서 `_print_analyst_view` 뒤에 `input("승인하려면 y: ")`
  분기 하나 — 미승인이면 run_reject와 동일 종료. run_demo.py만 수정, 계약 개정 불필요
  (§6은 발급 위치만 규정). 6절 안건 중 최소 비용.
- **해소 이력 (2026-07-10, 커밋 a622695)**: 위 "고치려면" 그대로 구현됐다.
  `run_approve`가 분석관 화면 출력 후 `input("승인하려면 y 입력: ")`으로 정지하고,
  y 외 입력이면 토큰을 발급하지 않는다 — run_reject와 동일 종료(그래프 interrupt 잔류,
  배포 산출물 없음). `tests/test_approve_gate.py` 2건
  (`test_non_y_input_rejects_without_issuing`, `test_y_input_issues_token_and_resumes`)이
  이 분기를 고정한다. 원문을 삭제하지 않고 남기는 이유: 이 `input` 분기가 왜
  존재하는지(자동 승인이 "20타수 8안타" 배포의 직접 경로였다)가 유지보수 정보다.

### 4.6 RAG 더미 3건 미구현 — feltner 정성노트 부재, §7 미충족

- **증상**: §7의 feltner 섹션 정의는 "정성노트('과거 관찰(작성시점)' 라벨)"를 포함하나,
  배포본에 정성노트가 없다. `rag_notes`는 BriefState에 존재하지만 `initial_state`가
  `[]`로 넣은 뒤 어떤 노드도 채우지 않고, synthesize도 소비하지 않는다 — 죽은 필드다.
- **근본 원인**: SESSIONS.md S7이 "RAG 더미 3건(시간 없으면 생략)"으로 명시적 생략을
  허용했고, 생략됐다.
- **왜 안 고쳤는가**: 시간. 그리고 뒤늦게 드러난 설계 충돌 — rag_notes는 verifier corpus
  (tool_results 직렬화)에 포함되지 않으므로, **정성노트의 숫자를 draft가 인용하는 순간
  §5가 FAIL을 낸다**. 구현은 "3건 넣기"가 아니라 corpus 편입 여부(§5 개정) 또는
  "노트는 무숫자 텍스트로 제한" 규약 신설을 요구한다.
- **고치려면**: ① rag_notes를 채우는 소스 결정(하드코딩 더미 3건이 MVP 정의) ②
  synthesize의 feltner 프롬프트에 관찰시점 라벨과 함께 주입(R2 준용 — JSON 블록) ③
  숫자 처리 규약 결정(§5 개정 or 무숫자 제한) ④ §6의 명문 트리거 발동 — rag_notes가
  외부 텍스트를 수용하는 시점에 연봉/사생활 축 재도입 검토 + 간접 인젝션 방어.

### 4.7 `Command(resume="")` 우회 — langgraph 1.2.8 버그 회피

- **증상**: `run_deploy_without_token`이 "토큰 없음"을 `Command(resume=None)`이 아니라
  `Command(resume="")`로 표현한다.
- **근본 원인**: langgraph 1.2.8에서 `resume=None` 재개가 내부 `UnboundLocalError`를
  일으킨다. 빈 문자열은 `hitl_gate`의 `bool(token)` 검사에서 의미상 동일(부재 토큰 →
  approved=False)이라 우회로 채택됐다.
- **왜 안 고쳤는가**: 상류(langgraph) 버그라 로컬에서 고칠 수 없고, 작성 시점에는
  requirements가 버전을 고정하지 않아(`langgraph` 무버전) 업그레이드 시점도 통제
  밖이었다.
- **부분 해소 (2026-07-10, 커밋 a622695)**: `requirements.txt`에 `langgraph==1.2.8`
  고정 완료 — "새 langgraph가 interrupt 의미론을 조용히 바꾸는" 큰 쪽 리스크는 닫혔다.
- **미해결 잔여**: 업그레이드 시 이 우회의 존속 여부를 확인하는 테스트
  (resume=None 왕복)는 여전히 없다. 버전을 올리는 세션은 `Command(resume=None)` 재개가
  `UnboundLocalError` 없이 동작하는지 확인한 뒤 `resume=""` 우회의 존폐를 결정할 것.

### 4.8 승인 키 미설정 시 프로세스 한정 랜덤 키 — 서명 검증이 실질 무의미

- **증상**: `SCOUTBRIEF_APPROVAL_SECRET` 미설정이면 `run_demo._ensure_demo_secret`이
  `secrets.token_hex()`로 키를 만들어 **같은 프로세스의 env**에 넣는다. 발급(콘솔)과
  검증(hitl_gate)이 같은 프로세스이므로 항상 검증이 성공한다 — 키가 무엇이든, 누가
  실행하든. HMAC이 보증하는 것은 "이 프로세스가 방금 서명했다"뿐이다.
- **근본 원인**: 단일 프로세스 데모 전제(§6 명문: replay 방어 MVP 범위 밖). 위조·변조
  차단(다른 키·내용 변경 거부)은 성립하지만, **발급 권한의 분리**는 키가 프로세스
  밖(운영자만 아는 env)에 있을 때만 성립하는데 데모 편의가 그 전제를 기본값에서 무너뜨린다.
- **왜 안 고쳤는가**: 키 미설정 시 즉시 실패(PermissionError)로 하면 데모 5명령이 전부
  사전 셋업을 요구해 시연 리스크가 커진다고 판단했다. `hitl._approval_secret`은 실제로
  즉시 실패하도록 짜여 있고(`test_missing_secret_raises`), 완화는 run_demo 계층에서만
  일어난다 — 모듈 경계는 지켜졌으나 실행 표면에서는 뚫려 있다.
- **고치려면**: 랜덤 키 생성 시 경고를 "보안 무효" 수준으로 격상하거나, --approve에
  한해 명시적 키를 요구(미설정 시 거부)한다. 운영 전환 시에는 발급을 별도 프로세스
  (분석관 CLI)로 분리해야 HMAC이 권한 분리로서 의미를 가진다.

### 4.9 (부수) 레드팀 테스트 1건의 주석이 실제와 다른 메커니즘을 설명한다

- **증상**: `test_redteam_fraction_slash_korean_boundary_not_stripped`의 주석은 층1
  슬래시 패턴에 `\b`가 있어 "3/4이닝"이 소거되지 않고 corpus 일치로 통과한다고
  설명한다. 실제 `verifier._STRIP_PATTERNS`의 패턴은 `\d{1,2}/\d{1,2}`로 `\b`가 없고,
  "3/4이닝"의 "3/4"는 **소거된다**(실행으로 확인: 정규화 결과 "이닝 투구", 추출 숫자
  없음). 테스트는 주석과 다른 이유로 통과한다.
- **문제인 이유**: 버그 문서화 테스트는 층1 수정 세션의 작업 목록 역할을 한다(2절).
  존재하지 않는 버그를 문서화한 항목은 그 세션을 오도한다. 역으로, `\b` 없는 현행
  패턴은 "3/4이닝"(분수)을 날짜로 오소거하는 **과잉 소거**이기도 하다 — 소거된 분수
  자리에 어떤 날조 분수를 넣어도 통과한다는 별개의 맹점이 있다.
- **고치려면**: 층1 수정 세션에서 이 테스트의 주석·의도를 재작성하고, "임의 분수
  `N/M` 소거 통과" 케이스로 교체한다.

### 4.10 원자료-전사 — 날조 없이 §5를 통과하는 무의미 출력 (2026-07-10 관측)

- **증상**: P4 모델 비교(gpt-5.4-mini, --linear 5회)에서 2회, feltner 섹션이 집계
  서술 대신 T1 투구 단위 원자료를 전량 나열했다(약 15만 자). 숫자가 전부 corpus
  실재값이라 §5는 원리상 PASS — 리포트로서는 사용 불가다(logs/runs.md).
- **근본 원인**: §5는 숫자의 실재만 보고 **품질·분량은 보지 않는다**. 기존에 알려진
  맹점은 "실재하는 숫자를 틀린 의미로 쓰는" 의미 계층(4.2~4.4)이었는데, 이것은
  "실재하는 숫자를 무의미한 형태로 쏟아내는" 분량·형식 계층 — §5 맹점의 신규
  클래스다.
- **왜 안 고쳤는가**: 모델 교체 실험에서 처음 관측된 클래스로, 현행 기본 모델
  (gpt-4o-mini)에서는 10회 실행 누적 0건이다. 기본 경로에 미발생인 결함의 게이트를
  실측 없이 넣는 것은 보류했다.
- **고치려면**: 길이 상한류의 **결정론 게이트**(섹션별 draft 길이 상한 검사).
  §5 개정 필요 여부 판정: 게이트를 verify 노드에 편입하면 §5가 "숫자 실재 대조"를
  넘어서므로 §5 개정 사안이고, verify와 별개의 결정론 검사(synthesize 직후 또는
  별도 노드)로 두면 §5 문면은 유지되나 §2 노드·배선 개정 검토가 필요하다. 실패
  처리도 정의해야 한다 — 길이 초과를 재생성 루프에 태울지(retry_counts 공유 여부)
  escalate로 보낼지가 §5/§2 어느 쪽으로 붙느냐에 따라 달라진다.

### 4.11 지시문-혼잡 — 지시 추가가 기존 지시의 이행을 밀어낸다 (2026-07-10 관측)

- **증상**: P5 배포본의 feltner 구종 패턴 표가 count_group=ALL 6행뿐이다. S8 배포본은
  ALL/2K/AHEAD/BEHIND 24행이었고, 지시문(graph.py feltner)은 count_group별 표를
  여전히 요구한다 — P3에서 주자 스플릿 지시(비교 한정 서술·pitches 병기)를 추가한 뒤
  기존 지시의 이행이 탈락했다. gpt-5.4-mini #5의 주자 스플릿 서술 누락도 같은
  클래스로 소급 분류했다(logs/runs.md "지시문-혼잡").
- **근본 원인**: 지시 총량. 섹션 지시문은 결함이 관측될 때마다 방어 조항을 누적해
  왔는데(4.2 두 차례, P3 스플릿 조항), 지시가 늘수록 개별 지시의 이행 확률이
  떨어진다는 것이 이 관측의 내용이다. 프롬프트 방어의 한계 목록에 "방향 반전을 못
  막는다"(4.2)에 이어 **"지시 총량 자체가 비용"**이라는 축이 추가된다.
- **왜 안 고쳤는가**: P6 배포본 대조에서 관측된 직후다. 지시문 재배치·압축은 같은
  프롬프트 계층의 수정이라 4.2 전례(2차 실패)상 효과를 보장할 수 없다.
- **고치려면**: §7-A 템플릿화(6절 순위 2)가 이 클래스에도 해법이다 — 표처럼 형식이
  결정론인 산출물을 LLM 지시에서 회수해 코드로 생성하면, 지시 총량이 줄어 남은
  지시의 이행 여지가 커진다. 지시문 계층에서는 "지시를 더하는 수정"의 회귀 비용
  (기존 지시 탈락)을 수정 전 실측으로 확인하는 규율이 필요하다.

---

## 5. 확장 시나리오 — 무엇을 건드려야 하는가

각 시나리오: 건드릴 파일과 절 / **계약 개정 필요 여부 판정**.

### 5.1 상대 선발이 Feltner가 아닌 다른 투수로 바뀌면 — **계약 개정 필요**

- `config.py`: `FELTNER_ID` 값과 검증 주석("2026 COL 912행, 12/12경기…") — §1 문자 단위
  일치 계약이므로 CONTRACT.md §1 전문을 함께 개정해야 한다. **`SECTION_KEYS`의
  "feltner"가 선수명이다** — 키를 바꾸면 §1·§2(R3)·§7 연쇄 개정, 안 바꾸면 키와 실체가
  어긋난 채 남는다.
- `docs/CONTRACT.md` §3: 캐시 파일명 3개가 선수명을 포함한다(feltner_recent5,
  feltner_arsenal_2026, bvp_lee_feltner).
- 코드: `scripts/build_cache.py`(파일명 dict), `src/mcp_server.py`(경로 상수 4개 —
  ID 가드는 config 추종이라 자동), `scripts/validate_cache.py`(SCHEMAS 파일명),
  `src/graph.py` SECTION_SPECS의 산문("Ryan Feltner"), CLAUDE.md 프로젝트 절.
- 절차: 새 선발 확정은 data-scout로 검증(CLAUDE.md 규칙 8·10 — "경기 첫 투수=선발"
  휴리스틱의 오프너 취약성 때문에 12/12 같은 등판 패턴 검증 필수) → config·계약 개정 →
  `build_cache.py` 재실행 → `validate_cache.py` → `smoke_mcp.py`.

### 5.2 타자가 우타자로 바뀌면 (`stand=='L'` 기본 가정) — **계약 개정 필요, 사실상 전면**

좌타 가정은 상수 하나가 아니라 이름 체계 전체에 박혀 있다:
- §1: `LEE_JH_ID`, `VSL_LOW_N_PITCHES`, `VSL_XWOBA_IMPUTE` — 이름부터 vsL.
- §3 ④: `vsL_pitches_7d` 컬럼. §4: `vsL_xwoba`/`vsL_top2_usage`/`vsL_low_n` 필드,
  `lefty_flag`(좌타 매치업 관점의 좌완 표시 — 우타자면 의미가 반대로 뒤집힌다),
  threat_score의 "좌타억제력" 각주 문면.
- 코드: `src/mcp_server.py` `_bullpen_threat_rows`의 `season["stand"]=="L"` 필터,
  `src/graph.py`의 `batter_stand: "L"`(parse_request)·SYSTEM_PROMPT("이정후(좌타)")·
  feltner 지시문("stand가 'L'인 행 기본")·THREAT_FOOTNOTE, `src/labels.py` 배너 문면
  ("이정후"), `scripts/build_cache.py` `build_bullpen_7d`, `scripts/smoke_mcp.py`
  TOOL4_FIELDS, `run_demo.py` DEFAULT_REQUEST.
- 판정: §1·§3·§4·§7 동시 개정 + 캐시 재생성. 일반화하려면 stand를 config 상수로 승격하고
  필드명을 탈방향화(vsX)하는 §4 재설계가 필요하다 — "소비자 1명 고정"이라는 MVP 전제를
  푸는 일이라, 사실상 차기 버전 설계다.

### 5.3 Tool을 5번째로 추가하려면 — **계약 개정 필요 (§4 명문 금지)**

§4 제목이 "상한 4, 추가 금지"다. 개정 후 건드릴 곳:
- `src/mcp_server.py`: 신규 tool 함수 + 캐시(신규 파일이면 §3도 개정 + build/validate).
- `src/graph.py`: `TOOL_FOOTNOTES`에 "T5", `fetch_data`, 관련 SECTION_SPECS의 tools,
  SYSTEM_PROMPT 규칙 4("[T5] 이상을 만들지 않는다" 문면 갱신).
- **`src/verifier.py` 층1 `\[T[1-4]\]` → `\[T[1-5]\]`** — §5 문면 개정 동반. 이걸 빼먹으면
  [T5] 각주가 소거되지 않는데, 현재 "5"가 POLICY_CONSTANTS에 있어 우연히 통과한다
  (`test_redteam_undefined_footnote_T5...`가 이 우연을 문서화). [T6]이면 "6"이 corpus에
  있어야만 통과 — 각주가 검증 결과를 좌우하는 비일관이 생긴다.
- `src/hitl.py` `TOOL_SOURCES`, `run_demo.py` `TOOL_NAMES`, `scripts/smoke_mcp.py`,
  §2의 tool_results 키 목록.

### 5.4 리포트 섹션을 5번째로 추가하려면 — **계약 개정 필요 (§1·§2 R3·§7)**

- `config.py SECTION_KEYS` = §1 전문 + §2 R3("섹션 키는 SECTION_KEYS 외 추가 금지") +
  §7 섹션 구조 정의 — 세 곳 동시 개정.
- 코드: `src/graph.py` SECTION_SPECS에 새 항목(assert가 키 일치를 강제하므로 누락 즉사),
  섹션 지시문 작성.
- 자동 추종(수정 불필요): initial_state·verify·label_pass·escalate·deploy_markdown은
  전부 SECTION_KEYS를 순회한다.
- 테스트: `tests/test_routing.py`의 `CLEAN` 픽스처(명시적 4키 dict)에 새 키 추가 —
  없으면 `fake_chat`의 `CLEAN[key]` KeyError.

### 5.5 다른 LLM 모델로 바꾸려면 — **코드만 (모델명은 코드 0줄)**

- 같은 프로바이더 내 모델 교체: env `SCOUTBRIEF_LLM_MODEL`만. 프로바이더 교체:
  `src/llm.py` `chat()` 재작성. §1 명문으로 LLM 파라미터는 llm.py 소유라 계약 무관.
- **단, 진짜 비용은 코드가 아니다**: SECTION_SPECS의 방어 지시문(방향 반전 금지,
  null 처리, 값 해석 금지)은 gpt-4o-mini의 **관측된 실패 모드**에 맞춰 2회 개정된
  것이다(4.2). 모델이 바뀌면 실패 분포가 바뀐다 — 이것은 추정이 아니라 실측이다.
  2026-07-10 P4에서 --linear 5회×2모델(gpt-4o-mini vs gpt-5.4-mini)로 측정했다
  (logs/runs.md 집계 표 전문):

  | 실패 클래스 | gpt-4o-mini | gpt-5.4-mini | 방향 |
  |---|---|---|---|
  | 기계적 오류 (matchup-반복 / 날조 잔존) | 5건 / 1건 | 0건 / 0건 | ↓ 소멸 |
  | 의미 반전 합계 (bullpen-a·b + bvp) | 13건 / 5회 | 14건 / 5회 | ↔~↑ 잔존·증가 |
  | 원자료-전사 (4.10) | 0 | 2회 | **신규** |
  | feltner 섹션 유실·열화 (전사 2 + escalate 1) | 0 | **3/5회** | **신규** |

  상위 모델은 기계적 오류를 없앴지만 의미 반전은 줄이지 못했고(bvp-반전 4→6),
  **전사·유실이라는 새 실패 클래스**를 들여왔다 — 5회 중 3회는 feltner 섹션이
  리포트로 성립하지 않았다. "프롬프트 방어의 모델 종속성" 경고의 실물이 이것이다:
  방어 지시문은 이전 모델의 실패 분포에 최적화된 것이라, 모델 교체는 방어를
  무효화할 뿐 아니라 게이트 없는 신규 클래스(4.10)를 연다. 교체 시 리허설 반복
  측정(회귀 테스트가 없는 영역, 2절 말미)과 DEMO.md 장면 2 전제 재검증이 필수다.

### 5.6 실시간 데이터(`statcast(live)`)로 전환하려면 — **스위치는 코드 0줄, 운용은 별개**

- 스위치 자체는 존재한다: env `SCOUTBRIEF_LIVE=1`이면 4 Tool이 `scripts/build_cache.py`의
  build 함수들을 재사용해 실조회하고, 실패 시 캐시로 조용히 fallback한다
  (`except Exception: pass` — 사용자에게 live 실패가 보고되지 않는 것은 알아둘 것).
- 켰을 때 바뀌는 것: ① source가 "statcast(live)"(§4 허용 문면) ② **corpus가 실행마다
  달라져** 재현성·`--poison`의 corpus 비존재 assert 전제가 흔들린다 ③ Tool당
  `fetch_season_raw`가 시즌 전체를 조회해 수 분 소요 ④ pybaseball 드리프트 assert가
  런타임 실패 지점이 된다.
- "다른 경기의 실시간 프리뷰"로 확장하는 것은 별개 문제다: GAME_DATE_US·CACHE_END·
  TEAM_OPP 전부 §1 상수라 경기마다 계약 개정을 요구하는 현행 구조 자체를 바꿔야 한다
  (§1을 "상수"에서 "요청 파라미터"로 — 전면 개정).

### 5.7 verifier에 의미 검증을 넣으려면 — **계약 개정 필요 (§5 재설계)**

- §5가 "숫자의 실재만 본다"와 그 리스크 수용을 명문화하고 의미 검증을 §6 HITL 소관으로
  지정하므로, 의미 검증 도입은 §5 개정이자 §5/§6 경계의 재획정이다.
- 건드릴 것: `src/verifier.py`(설계 교체 — 6절 §5-C), `config.py POLICY_CONSTANTS`
  존폐(§1), `tests/test_verifier.py` 버그 문서화 4건 반전 + 신규 케이스,
  `src/hitl.py REVIEW_NOTICE`(분석관 안내 문구가 "숫자 실재만 확인했다"를 전제),
  docs/DEMO.md 장면 2(§5의 맹목이 시연 소재 — 문서 전제 무효화).
- 전제 조건이 하나 있다: 의미 검증은 draft의 숫자가 **어느 필드의 값인지** 알아야
  하는데, 현재 draft는 자유 산문이라 귀속 정보가 없다. 따라서 §5-C는 synthesize의
  출력 형식(구조화 인용) 변경 — 즉 §7과 A레인 프롬프트까지 얽힌 양 레인 작업이다.

---

## 6. MVP 이후 안건 — 우선순위와 비용

| 순위 | 안건 | 무엇을 | 왜 | 비용 (파일 / 계약 개정) | 위험 |
|---|---|---|---|---|---|
| 1 | ~~`--approve` 판단 지점 삽입~~ **완료 (2026-07-10, a622695)** | run_demo.run_approve에 승인/반려 입력 분기 — 구현됨, test_approve_gate 2건 고정 | HITL 형해화 해소(4.5 해소 이력). "20타수 8안타"가 배포된 직접 경로 | run_demo.py 1개 / 불필요 (실적: 계약 무관으로 완료) | 없음. 최소 비용 최대 정합 — 예측대로였다 |
| 2 | §7-A `⚑` 전략 문장 결정론 템플릿화 | bullpen(·gameplan) ⚑ 문단을 synthesize 후처리 코드로 생성, LLM에서 회수 | 방향 반전(4.2)의 발생원 제거 — 프롬프트 방어 2차 실패로 남은 유일한 코드 측 해법. **근거 3건 추가(2026-07-10)**: ① 모델 교체 무효 실측 — P4에서 방향 반전 13→14건, 모델 계층도 기각(4.2) ② 지시문-혼잡(4.11) — 지시를 늘리는 방어는 기존 지시 이행을 밀어내는 역비용이 실측됨, 템플릿화는 지시 총량을 줄이는 유일한 방향 ③ Romano bvp 0.895 반전 3회 재발(4.4) — 산발이 아니라 안정적 실패 모드 | graph.py + tests / **§7 개정** (⚑ 문장의 생성 주체 변경) | 표현력 손실 — 템플릿 문장은 순위·사실만 말할 수 있다. gameplan까지 템플릿화하면 섹션의 존재 의의(맞춤 서술) 약화 |
| 3 | §5-A 층2 문맥 인지 (숫자+단위) | 층2를 "값" 집합에서 "값+직후 단위" 검사로 — 정책 상수는 지정 단위(PA 등)와 결합할 때만 허용 | "20타수 8안타" 클래스(4.1) 차단. MAX_RETRY의 "2"가 야구 기록을 승인하는 구조 해소 | verifier.py, config.py, tests / **§5 개정** | 한국어 단위 열거의 불완전성 → false-fail. 개정 세션이 이 비용 때문에 한 번 보류한 안건 — 이번엔 배포본 실물(4.1)이 반대 근거 |
| 4 | RAG 더미 3건 | rag_notes 주입 + feltner 프롬프트 소비 + 숫자 규약 결정 | §7 미충족 해소(4.6) | graph.py, (guards.py) / **§5 또는 §7 개정** (rag 숫자의 corpus 지위) + §6 명문 트리거 발동(연봉/사생활 축 재도입 검토) | rag 텍스트는 첫 외부 입력 채널 — 간접 인젝션 표면 신설. 무숫자 제한이 안전하나 노트의 정보가치 제한 |
| 5 | §5-B 층3 corpus 우연 일치 | corpus의 1~2자리 수 우연 일치 축소 | "8안타"의 "8"류(4.1 후반) 차단 | — / §5 개정 | **단독 해법은 이미 기각됨**(corpus 제한은 false-fail만 증가, §5 명문). §5-C에 흡수되는 안건 — 별도 추진 비권장 |
| 6 | §5-C 필드 인지 대조 | draft의 수치 인용을 구조화(값+필드 경로)하고 verifier가 필드 값·단위·귀속까지 대조 | §5-A·B의 근본 해법이자 4.1~4.4 전 클래스에 걸치는 A·B 공통 해법 | verifier.py, graph.py(synthesize 출력 형식), nodes_b, tests, DEMO.md / **§5·§7 개정, 설계 교체** | 최대 규모. LLM에 구조화 출력을 강제하는 새 실패 모드(형식 위반) 신설. 재생성 루프·escalate 의미론 재정의 필요 |
| 7 | §4-A Tool 4에 `suppression_weight` 추가 | threat_score의 구성 요소를 필드로 노출 | LLM이 순위 근거를 수치로 확인 가능하게 | mcp_server.py, smoke_mcp, graph 지시문 / **§4 개정** | **효과 불확실 — 반례 있음**: 3회차 Vodnik("위협 1위 → 적극 공략")은 순위표에 순위 컬럼이 이미 있는데도 의미를 반전한 사례다. 순위 필드 추가가 이 클래스를 막는다는 근거가 없다. 역효과는 확실: 1~N의 한 자리 정수가 corpus에 추가돼 §5 화이트리스트가 실질 확장된다(2절 mcp_server 항목). **보류 권고** — §7-A(순위 서술 자체의 템플릿화)가 같은 목표의 확실한 경로 |

순위 근거: 1은 완료됐다(2026-07-10). 2는 배포 사고(4.2·4.4)의 재발 경로를 직접 막는
잔여 최우선 안건으로, 프롬프트 방어·모델 교체가 모두 실측으로 기각된 지금 유일하게
남은 코드 측 해법이다. 3은 계약 개정이 필요하나 클래스 차단 효과가 실증됐다(배포본
실물 + P4 재발). 4는 §7 완결성. 5·7은 효과가 기각됐거나 불확실해 후순위·보류.
6은 올바른 종착지지만 단독 세션 규모가 아니다. 신규 결함 4.10(원자료-전사)의 길이
게이트는 현행 기본 모델에서 미발생이라 안건 표에 넣지 않았다 — 모델 교체 세션이
발동 조건이다(5.5).

---

## 부록 — 이 문서가 의존한 검증

- 파일 경로·함수명·상수값은 전부 현행 코드에서 직접 확인했다 (최초 작성:
  2026-07-10 브랜치 docs/architecture 기준. 2026-07-10 갱신분(4.5 해소·4.7 부분
  해소·4.10·4.11·5.5 실측 표)은 브랜치 exp/allin-runner-split 기준으로 재검증).
- 층1 소거 동작("12볼"→"1", "[T5]" 미소거, "3/4이닝" 소거, "20타수 8안타"→{"20","8"})은
  `src.verifier._normalize`/`_extract_numbers` 실행으로 재현했다.
- 배포본 인용(20타수 8안타 / 5타수 2안타 4행 반복 / Romano 0.895 "주의 필요")은
  S8 시점의 `out/brief_COL_SF_2026-07-09.md`에서 확인했다. **주의: out/는 git
  미추적이라 이 파일은 P5 --approve 재실행(2026-07-10)으로 덮어써졌다** — S8 배포본
  원문은 잔존하지 않으며, 인용의 전거는 logs/runs.md S8 행(소급 기재)이다. P5 배포본
  자체의 관측(0.405 귀속 오류·산문 구속 귀속 모호·count_group 표 축소)은 현존 파일과
  logs/runs.md P5 행에서 확인 가능하다.
- 테스트는 갱신 시점 기준 54건, `pytest --collect-only`로 확인했다 (verifier 20 /
  routing 11 / hitl 9 / guards 7 / arsenal_split 5 / approve_gate 2. 최초 작성 시점
  47건에서 p1 approve_gate 2건·p3 arsenal_split 5건 추가).
- 최초 작성 시점의 제언 "이후 리허설에서는 실행별 관측을 기록으로 남길 것"은
  `logs/runs.md`로 **이행됐다** (p1 커밋 a622695 신설, 이후 S8 소급 기재 + P4
  --linear 10회 + P5 --approve까지 실행별 기재). 이 문서 4절의 2026-07-10 갱신분이
  인용하는 건수·재발 횟수는 전부 그 로그가 전거다.
