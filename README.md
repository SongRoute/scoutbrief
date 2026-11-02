# ScoutBrief

경기 전 상대 분석 리포트를 자동으로 쓰는 LLM 에이전트. 숫자가 원자료에 실제로 있는지는 결정론적 검증기가 보고, 해석이 맞는지는 사람이 승인한 뒤에만 배포합니다.

2026 대학 과제(LLM·RAG AI 서비스 고도화), 2인 팀. 대상 경기는 COL @ SF(2026-07-09), 독자는 좌타자 이정후 한 명으로 고정한 MVP입니다.

## 구조

```
Statcast (빌드 시 1회) → build_cache.py → cache/*.csv (읽기 전용)
  → MCP 서버 4 Tool → synthesize (LLM, 섹션 4개)
  → verify (결정론, 숫자 실재 대조) → 실패 섹션만 재생성 (최대 2회) → 소진 시 escalate
  → label_pass (민감정보 마스킹) → hitl_gate (사람이 HMAC 토큰 발급) → render_deploy
```

| 설계 결정 | 이유 |
|---|---|
| 반올림·집계는 캐시 빌드에서만 | LLM과 Tool이 숫자를 바꾸지 못하게 해 검증 대상을 하나로 고정 |
| 검증기·위협 점수·소표본 라벨은 코드로만 | 판정에 LLM을 쓰지 않음 (OWASP LLM Top 10 대응) |
| 승인 토큰은 그래프 밖 콘솔이 발급 | 파이프라인이 스스로 배포를 승인할 수 없게 함 (LLM08) |
| 실패 섹션만 재생성 | 통과한 섹션은 보존해 재시도 비용과 흔들림을 줄임 |

기술: Python · LangGraph 1.2.8 · MCP · OpenAI · pybaseball 2.2.7 · pytest(테스트 54개)

## 무엇을 배웠나

검증기를 통과한 초안도 틀릴 수 있다는 것을 실행 로그로 기록했습니다([logs/runs.md](logs/runs.md)).

- **날조 통과**: 실제 "5타수 2안타"가 "20타수 8안타"로 바뀌었는데, 20은 정책 상수, 8은 다른 행 값과 우연히 일치해 검증을 통과
- **방향 반전**: 투수가 강하다는 지표를 "적극 공략 대상"으로 서술
- **지시문 혼잡**: 지시를 추가할수록 기존 지시가 산출물에서 빠짐

→ 숫자의 **실재**는 기계가, 숫자의 **의미**는 사람이 맡는 현재 구조의 근거가 됐습니다.

## 실행

```bash
pip install -r requirements.txt
pytest                              # 전체 테스트
python scripts/validate_cache.py    # 캐시 스키마·불변식 검증
python run_demo.py --linear         # E2E 관통
python run_demo.py --approve        # 사람 승인 → 배포
```

문서: [아키텍처](docs/ARCHITECTURE.md) · [계약](docs/CONTRACT.md) · [시연](docs/DEMO.md) · [세션 기록](docs/SESSIONS.md)
