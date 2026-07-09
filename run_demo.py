# run_demo.py — E2E 데모 러너 (CLAUDE.md 명령 표면)
# S4: --linear (선형 관통, 4섹션 draft + verify 리포트 콘솔 출력).
# --poison(S5), --deploy-without-token / --approve(S6)는 해당 세션에서 구현.
import argparse
import sys

import config
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
    print(f"\n4섹션 draft 생성 완료. verify FAIL {n_fail}건 — draft는 유지(S4 계약).")


def main() -> None:
    parser = argparse.ArgumentParser(description="ScoutBrief E2E 데모")
    parser.add_argument("--linear", action="store_true",
                        help="parse→fetch→synthesize→verify 선형 관통 (S4)")
    parser.add_argument("--poison", metavar="섹션",
                        help="오염→재생성 루프 데모 (S5에서 구현)")
    parser.add_argument("--deploy-without-token", action="store_true",
                        help="LLM08 차단 재현 (S6에서 구현)")
    parser.add_argument("--approve", action="store_true",
                        help="HITL 승인→배포 (S6에서 구현)")
    args = parser.parse_args()

    if args.poison:
        sys.exit("--poison은 S5(재생성 루프)에서 구현됩니다 — docs/SESSIONS.md 참조.")
    if args.deploy_without_token or args.approve:
        sys.exit("--deploy-without-token/--approve는 S6(HITL/LLM08)에서 구현됩니다 — docs/SESSIONS.md 참조.")
    if args.linear:
        run_linear()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
