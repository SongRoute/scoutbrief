# run_demo.py — E2E 데모 러너 (CLAUDE.md 명령 표면)
# S4: --linear (선형 관통, 4섹션 draft + verify 리포트 콘솔 출력).
# S5: --poison <섹션> (1차 draft 오염 → verify FAIL → 재생성 루프 로그).
# --deploy-without-token / --approve(S6)는 해당 세션에서 구현.
import argparse
import json
import sys

import config
from src import nodes_b
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


def main() -> None:
    parser = argparse.ArgumentParser(description="ScoutBrief E2E 데모")
    parser.add_argument("--linear", action="store_true",
                        help="parse→fetch→synthesize→verify 선형 관통 (S4)")
    parser.add_argument("--poison", metavar="섹션",
                        help="오염→재생성 루프 데모 (S5): 섹션 1차 draft에 날조 수치 주입")
    parser.add_argument("--deploy-without-token", action="store_true",
                        help="LLM08 차단 재현 (S6에서 구현)")
    parser.add_argument("--approve", action="store_true",
                        help="HITL 승인→배포 (S6에서 구현)")
    args = parser.parse_args()

    if args.poison:
        run_poison(args.poison)
        return
    if args.deploy_without_token or args.approve:
        sys.exit("--deploy-without-token/--approve는 S6(HITL/LLM08)에서 구현됩니다 — docs/SESSIONS.md 참조.")
    if args.linear:
        run_linear()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
