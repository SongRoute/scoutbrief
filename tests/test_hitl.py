"""
test_hitl.py — S6 HITL/LLM08 (SESSIONS.md S6, CONTRACT §6).
토큰 왕복/위조/변조 차단, 미승인 deploy PermissionError, 페이로드 R1 준수,
LLM08 정적 검사(노드는 발급하지 않는다). 판정은 pytest가 한다 (CLAUDE.md 규칙 11).
"""
import inspect
import pathlib

import pytest

import config
from src import hitl

SECRET = "unit-test-secret"
OTHER_SECRET = "another-secret"
REPORT = "# 리포트 전문\n\n본문."
TAMPERED = REPORT + " (승인 후 변조)"


def test_token_roundtrip():
    token = hitl.issue_approval_token(REPORT, SECRET)
    assert hitl.verify_approval_token(token, REPORT, SECRET)


def test_forged_token_rejected():
    """위조: 다른 키로 서명한 토큰은 통과하지 못한다."""
    forged = hitl.issue_approval_token(REPORT, OTHER_SECRET)
    assert not hitl.verify_approval_token(forged, REPORT, SECRET)


def test_tampered_report_rejected():
    """변조: 승인 후 내용이 바뀌면 정상 발급 토큰도 무효 (approve-what-you-see)."""
    token = hitl.issue_approval_token(REPORT, SECRET)
    assert not hitl.verify_approval_token(token, TAMPERED, SECRET)


def test_empty_token_rejected():
    assert not hitl.verify_approval_token("", REPORT, SECRET)


def test_missing_secret_raises(monkeypatch):
    """키 미설정 시 발급 자체가 PermissionError — 조용한 fallback 없음."""
    monkeypatch.delenv(hitl.APPROVAL_SECRET_ENV, raising=False)
    with pytest.raises(PermissionError):
        hitl.issue_approval_token(REPORT)


def _state(approved: bool) -> dict:
    tool_results = {
        key: {"data": [], "source": f"statcast(cache:{config.CACHE_END})", "rows": 0}
        for key, _, _ in hitl.TOOL_SOURCES
    }
    return {
        "tool_results": tool_results,
        "draft": {k: f"## {k} 섹션" for k in config.SECTION_KEYS},
        "escalated_sections": [],
        "approved": approved,
        "final_report": "",
    }


def test_unapproved_deploy_raises():
    """LLM08: approved=False로 render_deploy 진입 → PermissionError."""
    with pytest.raises(PermissionError):
        hitl.render_deploy(_state(approved=False))


def test_approved_deploy_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(hitl, "OUT_DIR", tmp_path)
    update = hitl.render_deploy(_state(approved=True))
    out = tmp_path / hitl.OUT_FILENAME
    assert out.exists()
    assert update["final_report"] == out.read_text(encoding="utf-8")


def test_payload_excludes_verify_report():
    """R1: 인터럽트 페이로드에 verify_report가 없다 — 실패 신호는 escalated_sections만.
    계획 승인 범위(배포 후보 전문 + 원천 데이터 + 검토 안내)는 포함된다."""
    state = {**_state(False),
             "verify_report": {"feltner": {"pass": False, "mismatches": ["x"]}}}
    payload = hitl.build_interrupt_payload(state)
    assert "verify_report" not in payload
    assert set(payload) == {"review_notice", "report_md",
                            "escalated_sections", "tool_results"}


def test_llm08_nodes_do_not_issue():
    """LLM08 정적 검사: 그래프 노드(hitl_gate/render_deploy)와 배선(graph.py)에
    issue_approval_token 호출이 없다 — 발급은 그래프 외부(콘솔) 전용."""
    for fn in (hitl.hitl_gate, hitl.render_deploy):
        assert "issue_approval_token" not in inspect.getsource(fn)
    graph_src = (pathlib.Path(__file__).resolve().parents[1]
                 / "src" / "graph.py").read_text(encoding="utf-8")
    assert "issue_approval_token" not in graph_src
