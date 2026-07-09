"""
S5 재생성 루프 테스트 — 라우팅(nodes_b) 단위 + 그래프 재진입 통전.
LLM 호출 없음: src.graph.chat을 monkeypatch. fetch는 캐시 경로(읽기 전용·오프라인).
판정은 이 pytest가 한다 (CLAUDE.md 규칙 11).
"""
import re

import config
from src import graph as graph_mod
from src import nodes_b
from src.graph import SECTION_SPECS, build_graph, initial_state

REQUEST = "S5 루프 테스트 요청"

# 숫자 0개 → verifier 무조건 PASS 하는 정상 본문 (배너·고정 문구의 corpus 수치는 별개)
CLEAN = {
    "feltner": "## 선발 분석\n최근 폼은 안정적이다.",
    "matchup": "## 상대 전적\n표본 부족으로 경향만 참고한다.",
    "bullpen": "## 불펜 위협\n좌완 위주로 주의가 필요하다.",
    "gameplan": "## 공략 포인트\n⚑ 초구 공략을 노린다.",
}

# corpus·정책상수·층1 소거에 걸리지 않는 날조 수치 (테스트 픽스처)
FABRICATED = "987654.321"


def _zero_counts():
    return {k: 0 for k in config.SECTION_KEYS}


def _vr(**passes):
    """verify_report 픽스처 — 지정 안 한 섹션은 PASS."""
    return {
        k: {"pass": passes.get(k, True), "mismatches": []}
        for k in config.SECTION_KEYS
    }


def _section_of(user_prompt: str) -> str:
    for key, spec in SECTION_SPECS.items():
        if spec["instructions"] in user_prompt:
            return key
    raise AssertionError("프롬프트에서 섹션 식별 실패")


# ---------------------------------------------------------------------------
# 단위: split_failed / route_after_verify
# ---------------------------------------------------------------------------

def test_route_all_pass_is_done():
    state = {"verify_report": _vr(), "retry_counts": _zero_counts()}
    assert nodes_b.route_after_verify(state) == "done"


def test_route_fail_with_budget_is_regenerate():
    state = {"verify_report": _vr(feltner=False), "retry_counts": _zero_counts()}
    assert nodes_b.route_after_verify(state) == "regenerate"


def test_route_fail_exhausted_is_escalate():
    counts = _zero_counts()
    counts["feltner"] = config.MAX_RETRY
    state = {"verify_report": _vr(feltner=False), "retry_counts": counts}
    assert nodes_b.route_after_verify(state) == "escalate"


def test_route_mixed_prefers_regenerate():
    # retryable이 하나라도 있으면 재생성 — exhausted는 대기 (SESSIONS.md S5)
    counts = _zero_counts()
    counts["feltner"] = config.MAX_RETRY
    state = {"verify_report": _vr(feltner=False, matchup=False), "retry_counts": counts}
    assert nodes_b.route_after_verify(state) == "regenerate"


def test_split_failed_classifies_in_section_order():
    counts = _zero_counts()
    counts["bullpen"] = config.MAX_RETRY
    retryable, exhausted = nodes_b.split_failed(
        _vr(feltner=False, bullpen=False, gameplan=False), counts)
    assert retryable == ["feltner", "gameplan"]
    assert exhausted == ["bullpen"]


# ---------------------------------------------------------------------------
# 단위: escalate / 피드백·플레이스홀더 무숫자 (R4·정답 주입 금지)
# ---------------------------------------------------------------------------

def test_escalate_replaces_draft_and_records_sections():
    counts = _zero_counts()
    counts["gameplan"] = config.MAX_RETRY
    state = {
        "verify_report": _vr(gameplan=False),
        "retry_counts": counts,
        "draft": {k: f"본문 {k}" for k in config.SECTION_KEYS},
        "escalated_sections": [],
    }
    out = nodes_b.escalate(state)
    assert out["draft"]["gameplan"] == nodes_b.ESCALATE_PLACEHOLDER
    assert out["escalated_sections"] == ["gameplan"]
    assert out["draft"]["feltner"] == "본문 feltner"  # 비대상 보존


def test_regen_feedback_contains_no_digits():
    for key in config.SECTION_KEYS:
        assert not re.search(r"\d", nodes_b.build_regen_feedback(key))


def test_escalate_placeholder_contains_no_digits():
    assert not re.search(r"\d", nodes_b.ESCALATE_PLACEHOLDER)


# ---------------------------------------------------------------------------
# 통전: 재진입 → 재생성 → 재검증 (그래프 실제 관통, chat만 대체)
# ---------------------------------------------------------------------------

def test_regen_recovers_and_only_failed_section_is_regenerated(monkeypatch):
    calls = {k: [] for k in config.SECTION_KEYS}

    def fake_chat(system, user):
        key = _section_of(user)
        calls[key].append(user)
        if key == "feltner" and len(calls[key]) == 1:
            return f"## 선발 분석\n포심 평균 구속이 {FABRICATED}마일이라고 주장한다."
        return CLEAN[key]

    monkeypatch.setattr(graph_mod, "chat", fake_chat)
    state = build_graph().invoke(initial_state(REQUEST))

    expected_counts = _zero_counts()
    expected_counts["feltner"] = 1
    assert state["retry_counts"] == expected_counts
    assert state["escalated_sections"] == []
    assert all(state["verify_report"][k]["pass"] for k in config.SECTION_KEYS)
    assert state["draft"]["feltner"] == CLEAN["feltner"]

    # 선택적 재생성: 실패 섹션만 2회, 나머지는 1회
    assert len(calls["feltner"]) == 2
    for k in ("matchup", "bullpen", "gameplan"):
        assert len(calls[k]) == 1

    # 재생성 프롬프트: 구조적 피드백 포함, mismatch 값(정답·오답 모두) 미주입
    regen_prompt = calls["feltner"][1]
    assert nodes_b.build_regen_feedback("feltner") in regen_prompt
    assert FABRICATED not in regen_prompt


def test_retry_exhaustion_escalates_and_terminates(monkeypatch):
    calls = {k: 0 for k in config.SECTION_KEYS}

    def fake_chat(system, user):
        key = _section_of(user)
        calls[key] += 1
        if key == "gameplan":
            return f"⚑ 근거 없는 수치 {FABRICATED}를 계속 인용한다."
        return CLEAN[key]

    monkeypatch.setattr(graph_mod, "chat", fake_chat)
    # invoke가 반환하는 것 자체가 종료(무한루프 없음)의 증거 — recursion_limit 내 완주
    state = build_graph().invoke(initial_state(REQUEST))

    assert calls["gameplan"] == 1 + config.MAX_RETRY          # 총 최대 3회 생성
    assert state["retry_counts"]["gameplan"] == config.MAX_RETRY
    assert state["escalated_sections"] == ["gameplan"]
    assert state["draft"]["gameplan"] == nodes_b.ESCALATE_PLACEHOLDER  # R4, 숫자 없음
    for k in ("feltner", "matchup", "bullpen"):
        assert calls[k] == 1
        assert state["verify_report"][k]["pass"]


# ---------------------------------------------------------------------------
# 데모 계측: --poison 노드는 1차(retry_counts==0)에만 주입
# ---------------------------------------------------------------------------

def test_poison_node_injects_only_on_first_pass():
    from run_demo import POISON_NUMBER, _make_poison_node

    node = _make_poison_node("feltner")
    base = {
        "draft": {"feltner": "본문"},
        "tool_results": {"pitcher_recent": {"data": [], "source": "cache", "rows": 0}},
    }
    out = node({**base, "retry_counts": {"feltner": 0}})
    assert POISON_NUMBER in out["draft"]["feltner"]
    assert node({**base, "retry_counts": {"feltner": 1}}) == {}
