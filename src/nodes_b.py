"""
nodes_b.py — S5 재생성 루프의 B레인 노드 (SESSIONS.md B레인 온보딩 ③).
route_after_verify(라우팅) / escalate(R4 플레이스홀더) / build_regen_feedback(피드백 빌더).
verifier가 만든 verify_report를 소비할 뿐 — LLM 호출 없음, 결정론.

R1 주의: 이 모듈은 verify_report를 escalated_sections로 '변환'하는 당사자다.
하류 노드(label_pass/hitl_gate/render_deploy)는 escalated_sections만 읽는다.
"""
import config

# CONTRACT §2 R4 — escalate 플레이스홀더에 숫자를 넣지 않는다. 문면 고정.
ESCALATE_PLACEHOLDER = "⚠️ [수치 검증 실패 — 분석관 직접 작성 필요]"

# 재생성 피드백 — 고정 문면. FAIL 사유는 구조적 수준으로만 전달한다.
# mismatch 값·건수 등 어떤 숫자도 넣지 않는다 (정답 주입 금지 패턴).
_REGEN_FEEDBACK = (
    "[재생성 지시] 직전 초안이 수치 검증에 실패했다: 데이터 블록(JSON)에 존재하지 않는 "
    "수치가 포함되어 있었다. 초안을 처음부터 다시 작성하되, 모든 수치는 아래 데이터 "
    "블록에 있는 값만 표기된 자릿수 그대로 옮겨 쓰고, 재계산·유도·근사·기억에 의존한 "
    "수치를 절대 쓰지 마라."
)


def split_failed(verify_report: dict, retry_counts: dict) -> tuple[list[str], list[str]]:
    """실패 섹션을 (retryable, exhausted)로 분류 — 라우팅·재생성 대상의 단일 공급원.
    retryable = 실패 ∧ retry < MAX_RETRY (SESSIONS.md S5). 순서는 SECTION_KEYS."""
    retryable, exhausted = [], []
    for key in config.SECTION_KEYS:
        rep = verify_report.get(key)
        if rep is None or rep["pass"]:
            continue
        if retry_counts.get(key, 0) < config.MAX_RETRY:
            retryable.append(key)
        else:
            exhausted.append(key)
    return retryable, exhausted


def build_regen_feedback(section_key: str) -> str:
    """재생성 프롬프트 선두에 붙는 구조적 피드백. 특정 숫자를 절대 포함하지 않는다."""
    return _REGEN_FEEDBACK


def route_after_verify(state) -> str:
    """조건 엣지: retryable 있으면 그 섹션들만 재생성, retryable 없이 실패가 남으면
    전부 escalate, 전부 PASS면 done (SESSIONS.md S5 라우팅)."""
    retryable, exhausted = split_failed(state["verify_report"], state["retry_counts"])
    if retryable:
        return "regenerate"
    if exhausted:
        return "escalate"
    return "done"


def escalate(state) -> dict:
    """retry 소진 섹션: draft를 R4 플레이스홀더로 교체(날조 수치의 하류 유출 차단) +
    escalated_sections 기록. 원 mismatches는 verify_report(감사 로그)에 남는다."""
    _, exhausted = split_failed(state["verify_report"], state["retry_counts"])
    draft = dict(state["draft"])
    for key in exhausted:
        draft[key] = ESCALATE_PLACEHOLDER
    merged = set(state["escalated_sections"]) | set(exhausted)
    escalated = [k for k in config.SECTION_KEYS if k in merged]
    return {"draft": draft, "escalated_sections": escalated}
