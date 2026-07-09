"""
test_approve_gate.py — run_demo --approve의 분석관 판단 지점 (exp/allin-runner-split P1).
비승인 입력이면 토큰 미발급·재개 없음(반려 = 토큰 미발급, CONTRACT §6),
y 입력이면 콘솔 발급 토큰으로 Command(resume=토큰) 재개.
발급 위치 불변식(그래프 노드 미발급)은 test_hitl.test_llm08_nodes_do_not_issue가 지킨다.
"""
from langgraph.types import Command

import run_demo
from src import hitl


class _FakeSnapshot:
    next = ("hitl_gate",)
    values: dict = {}


class _FakeGraph:
    def __init__(self, out_dir=None):
        self.invoked = []
        self._out_dir = out_dir

    def get_state(self, cfg):
        return _FakeSnapshot()

    def invoke(self, cmd, cfg):
        self.invoked.append(cmd)
        if self._out_dir is not None:  # render_deploy의 기록을 흉내 — assert 대상
            (self._out_dir / hitl.OUT_FILENAME).write_text("배포본", encoding="utf-8")
        return {"approved": True, "final_report": "배포본"}


_PAYLOAD = {
    "review_notice": "검토 안내",
    "report_md": "# 배포 후보 전문",
    "escalated_sections": [],
    "tool_results": {},
}


def _issue_spy(calls):
    def spy(report_md, secret=None):
        calls.append(report_md)
        return "spy-token"
    return spy


def test_non_y_input_rejects_without_issuing(monkeypatch, capsys):
    """비승인 입력(n): issue_approval_token 미호출, 그래프 재개 없음, 반려 메시지."""
    monkeypatch.setenv(hitl.APPROVAL_SECRET_ENV, "test-secret")
    fake = _FakeGraph()
    monkeypatch.setattr(run_demo, "_run_to_gate", lambda: (fake, _PAYLOAD))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    calls = []
    monkeypatch.setattr(hitl, "issue_approval_token", _issue_spy(calls))

    run_demo.run_approve()

    assert calls == []
    assert fake.invoked == []
    assert "분석관 반려 — 승인 토큰 미발급" in capsys.readouterr().out


def test_y_input_issues_token_and_resumes(monkeypatch, tmp_path, capsys):
    """y 입력: 검토한 전문(report_md)으로 발급 1회, Command(resume=토큰) 재개."""
    monkeypatch.setenv(hitl.APPROVAL_SECRET_ENV, "test-secret")
    monkeypatch.setattr(hitl, "OUT_DIR", tmp_path)
    fake = _FakeGraph(out_dir=tmp_path)
    monkeypatch.setattr(run_demo, "_run_to_gate", lambda: (fake, _PAYLOAD))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    calls = []
    monkeypatch.setattr(hitl, "issue_approval_token", _issue_spy(calls))

    run_demo.run_approve()

    assert calls == [_PAYLOAD["report_md"]]
    assert len(fake.invoked) == 1
    cmd = fake.invoked[0]
    assert isinstance(cmd, Command) and cmd.resume == "spy-token"
