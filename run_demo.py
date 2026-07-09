# run_demo.py — E2E 데모 러너 (CLAUDE.md 명령 표면)
# S4: --linear (선형 관통, 4섹션 draft + verify 리포트 콘솔 출력).
# S5: --poison <섹션> (1차 draft 오염 → verify FAIL → 재생성 루프 로그).
# S6: --deploy-without-token (LLM08 차단 재현) / --approve (HITL 승인→배포).
# 개정 2026-07-10: --reject (HITL 반려 = 토큰 미발급, CONTRACT §6).
#     이 파일이 곧 "그래프 외부 콘솔"이다 — issue_approval_token은 여기서만
#     호출된다 (CONTRACT §6 LLM08; 노드 미호출은 test_hitl 정적 검사가 보증).
import argparse
import json
import os
import secrets
import sys

from langgraph.types import Command

import config
from src import hitl, nodes_b
from src.graph import TOOL_FOOTNOTES, build_graph, initial_state

DEFAULT_REQUEST = (
    f"{config.GAME_DATE_US} {config.TEAM_OPP} @ {config.TEAM_US} 프리뷰 — 이정후 맞춤 리포트"
)

# §4 Tool 이름 (각주 번호 순) — 헤더 출처 표기용
TOOL_NAMES = {
    "pitcher_recent": "get_pitcher_recent",
    "arsenal": "get_pitch_arsenal",
    "bvp": "get_batter_vs_pitcher",
    "bullpen_threats": "get_bullpen_threats",
}


def _header(tool_results: dict) -> str:
    """§7 헤더 공통 — 각주 [T1]~[T4] + source 메타 + 승인 대기 상태 (결정론)."""
    lines = [
        f"# {config.TEAM_OPP} @ {config.TEAM_US} 프리뷰 — 이정후 ({config.GAME_DATE_US})",
        "",
        "상태: **분석관 승인 대기**",
        "",
        "출처:",
    ]
    for key, tag in TOOL_FOOTNOTES.items():
        src = tool_results[key]["source"]
        rows = tool_results[key]["rows"]
        lines.append(f"- [{tag}] {TOOL_NAMES[key]} — {src}, rows={rows}")
    return "\n".join(lines)


def run_linear() -> None:
    graph = build_graph()
    state = graph.invoke(initial_state(DEFAULT_REQUEST))

    print("=" * 72)
    print(_header(state["tool_results"]))
    for key in config.SECTION_KEYS:
        print("\n" + "-" * 72)
        print(f"[섹션: {key}]\n")
        print(state["draft"][key])

    # verify 결과 — 감사 로그를 콘솔에 그대로 출력 (S4 목적은 관통 확인, 통과율 아님)
    print("\n" + "=" * 72)
    print("VERIFY 리포트")
    n_fail = 0
    for key in config.SECTION_KEYS:
        rep = state["verify_report"][key]
        status = "PASS" if rep["pass"] else "FAIL"
        print(f"  {key}: {status}")
        if not rep["pass"]:
            n_fail += 1
            for m in rep["mismatches"]:
                print(f"    - {m}")
    print(f"\n4섹션 draft 생성 완료. verify FAIL {n_fail}건, "
          f"retry_counts={state['retry_counts']}, "
          f"escalated_sections={state['escalated_sections']} (S5: FAIL은 재생성 후 잔존분).")


# --- --poison 데모 계측 (S5) ---------------------------------------------
# 날조 수치 리터럴은 데모 전용 오염 페이로드 — 테스트 픽스처와 동일 지위.
# 운영 코드 경로(그래프·Tool·프롬프트)에는 존재하지 않으며, 주입 전에
# tool_results corpus 비존재를 assert로 보증한다 (오염 데모 무효화 방지).
POISON_NUMBER = "111.73"
POISON_SENTENCE = f"\n\n(오염 주입) 그의 포심 평균 구속은 {POISON_NUMBER}마일에 달했다."


def _make_poison_node(section: str):
    """1차 생성분(retry_counts==0)에만 날조 수치 문장을 덧붙이는 데모 노드.
    재생성 후에는 무개입 — 루프가 정상 데이터로 회복하는 경로를 보여준다."""
    def poison_draft(state: dict) -> dict:
        if state["retry_counts"][section] != 0:
            return {}
        corpus = json.dumps(state["tool_results"], ensure_ascii=False)
        assert POISON_NUMBER not in corpus, "오염 토큰이 corpus에 실재 — 데모 무효"
        draft = dict(state["draft"])
        draft[section] = draft[section] + POISON_SENTENCE
        print(f"[poison] '{section}' 1차 draft에 날조 수치 주입")
        return {"draft": draft}
    return poison_draft


def run_poison(section: str) -> None:
    """오염→재생성 루프 데모: 노드 전이·verify 결과·retry_counts를 로그로 출력."""
    if section not in config.SECTION_KEYS:
        sys.exit(f"--poison 인자는 {config.SECTION_KEYS} 중 하나여야 합니다: {section!r}")

    graph = build_graph(poison_node=_make_poison_node(section))
    state = dict(initial_state(DEFAULT_REQUEST))

    print(f"--poison {section}: 오염 → verify FAIL → 재생성 루프 (MAX_RETRY={config.MAX_RETRY})")
    print("=" * 72)
    for step, event in enumerate(graph.stream(state, stream_mode="updates"), 1):
        for node, update in event.items():
            state.update(update or {})
            if node == "verify":
                rep = state["verify_report"]
                statuses = ", ".join(
                    f"{k}={'PASS' if rep[k]['pass'] else 'FAIL'}" for k in config.SECTION_KEYS)
                print(f"[{step}] verify      → {statuses}")
                for k in config.SECTION_KEYS:
                    for m in rep[k]["mismatches"]:
                        print(f"      {k} mismatch: {m}")
            elif node == "synthesize":
                print(f"[{step}] synthesize  → retry_counts={state['retry_counts']}")
            else:
                print(f"[{step}] {node}")

    print("=" * 72)
    print(f"종료 상태: retry_counts={state['retry_counts']}, "
          f"escalated_sections={state['escalated_sections']}")
    if state["escalated_sections"]:
        print(f"escalate 섹션 draft: {nodes_b.ESCALATE_PLACEHOLDER!r}")
    else:
        print(f"재생성 성공 — '{section}' 최종 draft:\n")
        print(state["draft"][section])


# --- S6 HITL/LLM08 데모 -----------------------------------------------------
# 체크포인터 재개용 스레드 식별자 — 단일 실행 데모라 고정값.
HITL_THREAD = {"configurable": {"thread_id": "hitl-demo"}}


def _ensure_demo_secret() -> None:
    """승인 키 준비: 환경변수 우선, 미설정 시 프로세스 한정 랜덤 키 생성.
    단일 프로세스 데모라 발급(콘솔)과 검증(hitl_gate)이 같은 env를 공유한다."""
    if not os.environ.get(hitl.APPROVAL_SECRET_ENV):
        os.environ[hitl.APPROVAL_SECRET_ENV] = secrets.token_hex()
        print(f"[hitl] {hitl.APPROVAL_SECRET_ENV} 미설정 — 프로세스 한정 랜덤 키 생성")


def _run_to_gate():
    """HITL 그래프를 hitl_gate의 interrupt까지 실행하고 분석관 페이로드를 꺼낸다."""
    graph = build_graph(with_hitl=True)
    state = graph.invoke(initial_state(DEFAULT_REQUEST), HITL_THREAD)
    payload = state["__interrupt__"][0].value
    return graph, payload


def _print_analyst_view(payload: dict) -> None:
    """분석관 화면 (계획 승인 범위): 배포 후보 전문 + escalated_sections +
    tool_results 원본(대조용) + 검토 안내. verify_report는 R1에 따라 없음."""
    print("=" * 72)
    print("[HITL 분석관 검토 화면]")
    print(f"\n{payload['review_notice']}")
    print(f"\nescalated_sections: {payload['escalated_sections']}")
    print("\n--- 배포 후보 전문 " + "-" * 53 + "\n")
    print(payload["report_md"])
    print("--- 대조용 원천 데이터 (tool_results 원본) " + "-" * 29 + "\n")
    print(json.dumps(payload["tool_results"], ensure_ascii=False))
    print("=" * 72)


def run_deploy_without_token() -> None:
    """LLM08 차단 재현: 관문까지 정상 진행 후 토큰 없이 배포 재개 → PermissionError."""
    _ensure_demo_secret()
    graph, payload = _run_to_gate()
    print(f"[hitl] 관문 도달 — escalated_sections={payload['escalated_sections']}")
    # resume=None은 langgraph 1.2.8 내부 버그(UnboundLocalError)를 건드린다 —
    # 빈 토큰("")으로 재개해도 의미 동일: 토큰 부재 → approved=False.
    print("[hitl] 승인 토큰 없이(빈 토큰) 배포 시도 → PermissionError 예상\n")
    graph.invoke(Command(resume=""), HITL_THREAD)  # render_deploy가 raise — 전파시킴


def run_approve() -> None:
    """HITL 승인→배포: 분석관 화면 표시 → 콘솔(이 함수)이 토큰 발급 →
    Command(resume=토큰) 재개 → render_deploy가 검증된 배포본을 out/에 기록."""
    _ensure_demo_secret()
    graph, payload = _run_to_gate()
    _print_analyst_view(payload)
    # LLM08: 발급은 그래프 외부(이 콘솔)에서만 — 서명 대상은 방금 검토한 전문.
    token = hitl.issue_approval_token(payload["report_md"])
    print(f"\n[hitl] 콘솔에서 승인 토큰 발급 (HMAC-SHA256): {token[:16]}…")
    state = graph.invoke(Command(resume=token), HITL_THREAD)
    out_path = hitl.OUT_DIR / hitl.OUT_FILENAME
    assert state["approved"] and out_path.exists()
    print(f"[hitl] 승인 확인(approved={state['approved']}) → 배포 완료: {out_path}")
    print(f"[hitl] final_report {len(state['final_report'])}자 기록")


def run_reject() -> None:
    """HITL 반려 데모 (CONTRACT §6): 분석관 화면 표시 후 토큰을 발급하지 않는다 —
    반려 = 토큰 미발급. 그래프는 interrupt에 잔류하고 배포 산출물은 생성되지 않는다.
    PermissionError 경로(--deploy-without-token)와 구분: 그쪽은 무효 토큰으로
    배포를 '시도'한 경우의 방어, 이쪽은 시도 자체가 없는 정상 반려."""
    _ensure_demo_secret()
    graph, payload = _run_to_gate()
    _print_analyst_view(payload)
    snapshot = graph.get_state(HITL_THREAD)
    assert snapshot.next, "그래프가 hitl_gate interrupt에 잔류해야 한다"
    assert not snapshot.values.get("final_report"), "반려 경로에 배포 산출물 금지"
    print("\n[hitl] 분석관 반려 — 승인 토큰 미발급. 그래프는 interrupt에 잔류, "
          "배포 산출물 없음 (CONTRACT §6: 반려 = 토큰 미발급).")


def main() -> None:
    parser = argparse.ArgumentParser(description="ScoutBrief E2E 데모")
    parser.add_argument("--linear", action="store_true",
                        help="parse→fetch→synthesize→verify 선형 관통 (S4)")
    parser.add_argument("--poison", metavar="섹션",
                        help="오염→재생성 루프 데모 (S5): 섹션 1차 draft에 날조 수치 주입")
    parser.add_argument("--deploy-without-token", action="store_true",
                        help="LLM08 차단 재현 (S6): 토큰 없이 배포 → PermissionError")
    parser.add_argument("--approve", action="store_true",
                        help="HITL 승인→배포 (S6): 콘솔 토큰 발급 → out/*.md 생성")
    parser.add_argument("--reject", action="store_true",
                        help="HITL 반려 (CONTRACT §6): 토큰 미발급 → 그래프 잔류, 배포 없음")
    args = parser.parse_args()

    if args.poison:
        run_poison(args.poison)
        return
    if args.deploy_without_token:
        run_deploy_without_token()
        return
    if args.approve:
        run_approve()
        return
    if args.reject:
        run_reject()
        return
    if args.linear:
        run_linear()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
