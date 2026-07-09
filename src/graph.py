# src/graph.py — S4 골격 + S5 재생성 루프 (A레인 배선, SESSIONS.md S4·S5)
# parse_request → fetch_data → synthesize → verify → route_after_verify
#   → regenerate(→synthesize) | escalate | done.
# 라우팅·escalate·피드백 빌더는 B레인 소유(src/nodes_b.py) — 여기서는 import만.
# HITL/deploy(S6), 가드레일(S7)은 이 파일에 아직 없다.
#
# B 모듈은 시그니처만 배선 (판정 로직·층1 패턴 수정 금지):
#   verifier.verify_report(draft: dict, tool_results: dict) -> verify_report
#   labels.small_sample_banner(pa_total: int) -> str
# label_pass 노드는 S5 범위 — 단, §7 matchup 배너는 결정론 라벨(규칙 4)이라
# synthesize의 후처리 코드로 부착한다. vsL_low_n은 Tool 4 필드를 소비, 재계산 금지.
#
# R2: tool_results 값의 f-string 개별 삽입 금지 — 프롬프트에는 툴 결과 전체의
#     json.dumps 직렬화 블록으로만 전달한다.
import json
import pathlib
import sys
from typing import TypedDict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config

from langgraph.graph import END, START, StateGraph

from src import labels, nodes_b, verifier
from src.llm import chat
from src.mcp_server import (get_batter_vs_pitcher, get_bullpen_threats,
                            get_pitch_arsenal, get_pitcher_recent)


class BriefState(TypedDict):
    request: str                    # LLM01 필터 통과 원문
    game_ctx: dict                  # MVP: config 상수 적재 (parse_request는 규칙 기반)
    tool_results: dict              # 키 고정: pitcher_recent | arsenal | bvp | bullpen_threats
                                    #   각 값: {"data": [...], "source": str, "rows": int}
    rag_notes: list[dict]           # [{"text": str, "observed_at": "YYYY-MM"}] — S7, 없으면 []
    draft: dict                     # 키 = SECTION_KEYS, 값 = 섹션 마크다운
    verify_report: dict             # 키 = SECTION_KEYS, 값 = {"pass": bool, "mismatches": [str]}
                                    #   ★ 감사 로그 전용. escalate 이후 하류에서 읽기 금지
    retry_counts: dict              # 키 = SECTION_KEYS, 기본 0
    escalated_sections: list[str]   # ★ 하류가 읽는 유일한 실패 신호
    approved: bool                  # hitl_gate만 쓴다. 초기 False
    final_report: str


# CONTRACT §4 Tool 번호 = 각주 번호. 상한 4 — [T5] 이상은 존재할 수 없다.
TOOL_FOOTNOTES = {
    "pitcher_recent": "T1",
    "arsenal": "T2",
    "bvp": "T3",
    "bullpen_threats": "T4",
}

# CONTRACT §4 각주 허용 문면 전문 — 수치 임계값 인용 금지 (Verifier 방어선 보호).
THREAT_FOOTNOTE = (
    "threat_score = 가용성×좌타억제력 (규칙 공식, config.py 정의), 감독 성향 미반영"
)

# §7 gameplan: 전달 금지 문구 — 결정론적으로 코드가 부착.
NO_FORWARD_NOTICE = "※ 내부 분석 문서 — 선수·외부 전달 금지."

# LLM 프롬프트 전용 뷰 — 캐시·§4 스키마는 동결이므로 원본에서 키만 개명한 파생본.
# 'n'은 구종별 투구수인데 자기설명적이지 않아 타수로 오독됨 → pitches로 개명.
# ★ verifier.verify_report에는 반드시 원본 tool_results를 넘긴다 (진실 공급원 단일).
LLM_VIEW_RENAMES = {
    "arsenal": {"n": "pitches"},
    "bvp": {"n": "pitches"},
}


def _llm_view(tool_key: str, tool_result: dict) -> dict:
    renames = LLM_VIEW_RENAMES.get(tool_key)
    if not renames:
        return tool_result
    data = [{renames.get(k, k): v for k, v in row.items()} for row in tool_result["data"]]
    return {**tool_result, "data": data}

SYSTEM_PROMPT = f"""너는 SF 자이언츠 전력분석 보조다. 상대(COL) 선발·불펜을 이정후(좌타) 관점에서
분석하는 프리뷰 리포트의 '한 섹션'을 한국어 마크다운으로 작성한다.

절대 규칙:
1. 숫자는 아래 데이터 블록(JSON)에 있는 값만, 표기된 자릿수 그대로 옮겨 쓴다.
   합산·평균·비율·백분율 변환 등 어떤 재계산·반올림·유도도 금지.
2. vsL_xwoba·xwoba·bvp_xwoba가 null인 항목에는 xwOBA 수치를 절대 쓰지 않는다 —
   "표본 부족"으로만 서술한다. 순위 계산용 내부 대입값이 존재하지만,
   그 값은 어떤 경우에도 리포트에 수치로 나타나면 안 된다.
3. threat_score를 설명할 때는 정확히 이 각주 문구만 사용한다:
   "{THREAT_FOOTNOTE}"
   수치 임계값·가중치 세부·컷오프는 인용 금지.
4. 출처 각주는 [T1]~[T4]만 존재한다. [T5] 이상을 만들지 않는다.
   각 데이터 블록 앞의 [Tn] 표기가 그 블록의 각주 번호다 — 수치 인용 시 해당 [Tn]을 병기한다.
5. 관찰(데이터에 있는 사실)과 추정(해석·전략·예상)을 구분하고, 모든 추정 문장 앞에 ⚑를 붙인다.
6. 선수의 부상·결장·등판 공백의 사유를 추측하지 않는다. 수술·재활·진단 등 의료 상세 금지.
   데이터에 있는 등판 기록 사실만 기술한다.
7. 섹션 본문만 출력한다. 리포트 제목·공통 헤더·승인 상태 표기는 시스템 소유 — 쓰지 않는다.
   섹션 제목은 '## '로 시작하고 번호를 붙이지 않는다. 코드펜스로 감싸지 않는다.
8. 구종 코드 해석은 아래 사전만 사용한다. 사전에 없는 코드는 코드 그대로 표기한다:
   CH=체인지업, CU=커브, FC=커터, FF=포심 패스트볼, SI=싱커, SL=슬라이더, ST=스위퍼
9. xwOBA 해석 방향 — 타자 관점 지표다. 높을수록 타자에게 유리하고 투수에게 나쁘다.
   - 투수 기록의 xwOBA가 높다 → 그 투수가 해당 타자군에게 약하다 (타자의 공략 대상).
   - 투수 기록의 xwOBA가 낮다 → 그 투수가 해당 타자군을 잘 억제한다 (타자에게 까다롭다).
   주어와 방향을 일치시켜라. 투수의 vsL xwOBA가 높은데 '좌타가 약하다'거나
   '좌타 상대 강한 모습'이라고 쓰면 방향이 반대다 — 금지."""

SECTION_SPECS = {
    "feltner": {
        "tools": ["pitcher_recent", "arsenal"],
        "instructions": (
            "섹션: 선발 Ryan Feltner 분석.\n"
            "- [T1] 최근 5경기 투구 단위 데이터로 최근 폼(경기별 구속·구종 구성 흐름)을 서술.\n"
            "- [T2] 아스널에서 stand가 'L'(좌타 상대)인 행을 기본으로, count_group"
            "(ALL/2K/AHEAD/BEHIND)별 구종 패턴을 표로 정리. 우타(stand 'R') 수치는 쓰지 않는다.\n"
            "- usage_pct·avg_velo·xwoba·zone_top2는 JSON 값 그대로 인용."),
    },
    "matchup": {
        "tools": ["bvp", "arsenal"],
        "instructions": (
            "섹션: 이정후 vs Feltner 상대 전적.\n"
            "- 소표본 배너는 시스템이 별도로 삽입한다 — 직접 쓰지 마라.\n"
            "- [T3] 구종별 전적(pitches=투구수, xwoba — null이면 '표본 부족')을 정리하고, "
            "통산은 'X타수 Y안타' 형식으로 표기 — X는 ab_total, Y는 hits_total 값 그대로. "
            "pitches(투구수)는 타수가 아니다 — 타수·안타로 쓰지 마라.\n"
            "- [T2] 좌타 전체 상대 경향은 '보조 지표'임을 명시하고 참고로만 제시."),
    },
    "bullpen": {
        "tools": ["bullpen_threats"],
        "instructions": (
            "섹션: COL 불펜 위협 순위.\n"
            "- [T4] data 배열 전원을 주어진 순서 그대로(threat_score 내림차순) 순위표로. "
            "순서 변경·누락 금지.\n"
            "- 표 컬럼: 순위 / 투수(투구손, lefty_flag가 1이면 '(좌)' 표기) / "
            "만날 확률 근거(rest_days·appearances_7d·pitches_7d·last_game 사실) / "
            "vsL 주무기(vsL_top2_usage) / vsL xwOBA(null이면 '표본 부족') / "
            "개인 전적(bvp_xwoba — null이면 '-', bvp_pa를 PA로 병기).\n"
            "- 표 상단에 소표본 안내를 한 번만: vsL_low_n이 1인 투수는 시즌 vsL 표본 부족으로 "
            "xwOBA 해석에 주의. vsL_low_n은 필드 값 그대로 쓰고 재계산하지 않는다.\n"
            "- 표 아래에 상위 위협 투수별 대응 전략을 서술 — 전략 문장은 전부 추정이므로 ⚑. "
            "vsL xwOBA 해석은 규칙 9의 방향을 따른다 — 낮은 투수일수록 이정후에게 까다롭다.\n"
            "- threat_score 설명은 규칙 3의 각주 문구 그대로."),
    },
    "gameplan": {
        "tools": ["pitcher_recent", "arsenal", "bvp", "bullpen_threats"],
        "instructions": (
            "섹션: 이정후 맞춤 공략 포인트.\n"
            "- [T1]~[T4] 전체를 종합해 타석 접근 포인트(카운트별 노림수, 주의 구종, "
            "불펜 교체 국면 대비)를 항목별로 제시.\n"
            "- 모든 항목이 추정이므로 각 항목 앞에 ⚑.\n"
            "- 전달 금지 문구는 시스템이 삽입한다 — 직접 쓰지 마라."),
    },
}

assert set(SECTION_SPECS) == set(config.SECTION_KEYS), "R3: 섹션 키는 SECTION_KEYS 고정"


def parse_request(state: BriefState) -> dict:
    """규칙 기반 파싱 — MVP: config 상수 적재. LLM01 입력 필터는 S7."""
    if not state["request"].strip():
        raise ValueError("빈 request")
    return {"game_ctx": {
        "game_date": config.GAME_DATE_US,
        "team_us": config.TEAM_US,
        "team_opp": config.TEAM_OPP,
        "batter_id": config.LEE_JH_ID,
        "batter_stand": "L",
        "pitcher_id": config.FELTNER_ID,
    }}


def fetch_data(state: BriefState) -> dict:
    """MCP 4 Tool 호출 (캐시 우선 경로 — smoke_mcp가 오프라인 동작 보증)."""
    ctx = state["game_ctx"]
    return {"tool_results": {
        "pitcher_recent": get_pitcher_recent(ctx["pitcher_id"]),
        "arsenal": get_pitch_arsenal(ctx["pitcher_id"]),
        "bvp": get_batter_vs_pitcher(ctx["batter_id"], ctx["pitcher_id"]),
        "bullpen_threats": get_bullpen_threats(ctx["team_opp"], ctx["batter_id"]),
    }}


def _json_block(tool_key: str, tool_result: dict) -> str:
    """R2 — 툴 결과는 JSON 직렬화 블록으로만. 개별 값 f-string 삽입 금지.
    LLM에는 자기설명적 키의 뷰를 통째로 직렬화 — 원본은 verifier 몫."""
    body = json.dumps(_llm_view(tool_key, tool_result), ensure_ascii=False, indent=2)
    return "[" + TOOL_FOOTNOTES[tool_key] + "] " + tool_key + ":\n```json\n" + body + "\n```"


def _bvp_pa_total(tool_results: dict) -> int:
    """캐시 ③ pa_total(전 행 동일값 반복) — Tool 3 데이터를 소비, 재계산 없음."""
    rows = tool_results["bvp"]["data"]
    return int(rows[0]["pa_total"]) if rows else 0


def synthesize(state: BriefState) -> dict:
    """섹션별 LLM 생성 + 결정론 후처리(라벨·고정 문구 — 규칙 4: LLM에 맡기지 않음).
    S5 재생성 모드: verify_report가 있으면 retryable(실패∧retry<MAX_RETRY) 섹션만
    다시 생성하고 retry_counts를 올린다. PASS 섹션의 draft는 보존.
    재생성 프롬프트 = 구조적 피드백(숫자 미포함) + 기존 지시 + 기존 JSON 블록(R2)."""
    tr = state["tool_results"]
    is_regen = bool(state["verify_report"])
    retryable, _ = nodes_b.split_failed(state["verify_report"], state["retry_counts"])
    targets = retryable if is_regen else list(config.SECTION_KEYS)
    draft = dict(state["draft"])
    retry_counts = dict(state["retry_counts"])
    for key in targets:
        spec = SECTION_SPECS[key]
        blocks = "\n\n".join(_json_block(t, tr[t]) for t in spec["tools"])
        instructions = spec["instructions"]
        if is_regen:
            instructions = nodes_b.build_regen_feedback(key) + "\n\n" + instructions
            retry_counts[key] += 1
        draft[key] = chat(SYSTEM_PROMPT, instructions + "\n\n--- 데이터 ---\n\n" + blocks)
        # 결정론 후처리 — 섹션을 새로 쓸 때마다 재부착 (재생성 경로 포함)
        if key == "matchup":
            banner = labels.small_sample_banner(_bvp_pa_total(tr))   # §7 배너
            if banner:
                draft[key] = banner + "\n\n" + draft[key]
        if key == "gameplan":
            draft[key] = draft[key].rstrip() + "\n\n" + NO_FORWARD_NOTICE
    return {"draft": draft, "retry_counts": retry_counts}


def verify(state: BriefState) -> dict:
    """verifier.verify_report 배선. verify_report는 감사 로그 —
    라우팅(escalated_sections 채우기)은 S5의 route_after_verify 소유."""
    return {"verify_report": verifier.verify_report(state["draft"], state["tool_results"])}


def initial_state(request: str) -> BriefState:
    return BriefState(
        request=request, game_ctx={}, tool_results={}, rag_notes=[],
        draft={}, verify_report={},
        retry_counts={k: 0 for k in config.SECTION_KEYS},
        escalated_sections=[], approved=False, final_report="",
    )


def build_graph(poison_node=None):
    """S5: verify 뒤 조건 라우팅 — regenerate(→synthesize) / escalate / done.
    재생성마다 retryable 섹션의 retry_counts가 1씩 증가하므로 synthesize는
    최대 1+MAX_RETRY회 실행 — 구조적으로 무한루프 불가.

    poison_node: 데모 계측 훅(run_demo --poison 소유) — synthesize와 verify 사이에
    끼워 넣는 상태 함수. 운영 경로는 None."""
    g = StateGraph(BriefState)
    g.add_node("parse_request", parse_request)
    g.add_node("fetch_data", fetch_data)
    g.add_node("synthesize", synthesize)
    g.add_node("verify", verify)
    g.add_node("escalate", nodes_b.escalate)
    g.add_edge(START, "parse_request")
    g.add_edge("parse_request", "fetch_data")
    g.add_edge("fetch_data", "synthesize")
    pre_verify = "synthesize"
    if poison_node is not None:
        g.add_node("poison_draft", poison_node)
        g.add_edge("synthesize", "poison_draft")
        pre_verify = "poison_draft"
    g.add_edge(pre_verify, "verify")
    g.add_conditional_edges(
        "verify", nodes_b.route_after_verify,
        {"regenerate": "synthesize", "escalate": "escalate", "done": END},
    )
    g.add_edge("escalate", END)
    return g.compile()
