# ScoutBrief MVP — Claude Code 작업 규칙

## 프로젝트
COL @ SF (미국시간 2026-07-09) 프리뷰 리포트 자동 생성.
소비자는 이정후(좌타) 단 한 명. 모든 수치는 stand=='L' 스플릿이 기본, 전체 성적은 보조.
선발: Ryan Feltner (MLBAM 663372, COL, 확정 — 11/11경기 1회 등판 검증됨).
이정후: MLBAM 808982 (2026-06-25~07-08 statcast 156행으로 검증됨).
계약 문서: docs/CONTRACT.md (스키마·시그니처·상태), docs/SESSIONS.md (세션·완료조건).

## 절대 규칙
1. config.py의 상수 외 매직넘버 금지. 새 상수는 config에 추가 후 사용.
2. cache/*.csv는 읽기 전용. 재생성은 scripts/build_cache.py로만.
3. 반올림은 build_cache.py에서만. Tool과 LLM 프롬프트에서 반올림 금지.
4. Verifier·threat_score·소표본 라벨은 결정론적 코드. LLM 호출 금지.
5. BriefState 계약 (상세: CONTRACT.md):
   - 하류 노드(label_pass/hitl_gate/render_deploy)는 verify_report를 읽지 않는다.
     실패 신호는 escalated_sections만.
   - tool_results는 f-string 삽입 금지, JSON 직렬화 블록으로만 프롬프트 전달.
   - 섹션 키는 config.SECTION_KEYS 고정. 추가 금지.
6. 상대 레인 모듈 리팩터링 금지. 인터페이스 변경은 CONTRACT.md 개정 합의 후.
7. src/graph.py는 S4 전 생성 금지. 배선은 A레인 소유.
8. 사실 정보(선수/로스터/API 동작) 불명 시 추측 금지 — data-scout에 위임하거나 멈출 것.

## 서브에이전트 규칙
9. 커밋 전 contract-reviewer 호출은 의무. PASS 없이 커밋 금지.
10. 사실 확인은 data-scout에 위임 — 메인 컨텍스트에서 추측·즉석 조회 금지.
11. 검증·라벨·threat_score의 정합성 '판단'을 서브에이전트에 맡기지 않는다.
    판정은 pytest가 한다. 서브에이전트(verifier-redteam)는 테스트를 '생성'할 뿐.
12. 서브에이전트에 넘기는 프롬프트에 관련 파일 경로를 명시할 것 —
    서브에이전트는 이 대화를 보지 못한다.

## 레인 소유
- A: src/mcp_server.py, scripts/build_cache.py, scripts/validate_cache.py,
     src/guards.py, src/graph.py(S4부터)
- B: src/verifier.py, src/labels.py, src/hitl.py, src/nodes_b.py, tests/ 대부분
- 공유(개정은 합의 후): config.py, docs/*, .claude/agents/*

## 알려진 리스크 (수용됨)
- "경기 첫 투수 = 선발" 휴리스틱은 오프너/벌크에 취약 (Senzatela 오검출 사례 확인).
  → 리포트에 등판 메타(appearances_7d, last_game) 원문 노출, 분석관이 육안 필터.
- pybaseball 2.2.7 기준 statcast(team=)은 투구(수비) 기준 필터 — 경험적 검증.
  → requirements에 버전 고정 + build_cache의 assert가 드리프트 감지선.
- Feltner 4/23~5/30 등판 공백: 로스터 사실만 기술. 사유 추측·의료 상세 금지(LLM06).
- 이정후 vs Feltner는 극소표본 예상 → 소표본 라벨 + 좌타 전체 경향을 보조 지표로.

## 명령
pytest                              # 전체 테스트
python scripts/validate_cache.py    # 캐시 5파일 스키마·불변식 검증
python scripts/smoke_mcp.py         # MCP 4 Tool 스모크 (오프라인 재실행 포함)
python run_demo.py --linear         # E2E 선형 관통
python run_demo.py --poison <섹션>  # 오염→재생성 루프 데모
python run_demo.py --deploy-without-token   # LLM08 차단 재현
python run_demo.py --approve        # HITL 승인→배포