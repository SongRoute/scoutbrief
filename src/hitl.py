"""
hitl.py — S6 HITL/LLM08 (SESSIONS.md B레인 온보딩 ④).
interrupt 페이로드 빌더 / HMAC 승인 토큰 발급·검증 / render_deploy 게이트.

LLM08 (CONTRACT §6:171): issue_approval_token은 그래프 외부(콘솔)에서만 호출한다.
그래프 노드(hitl_gate/render_deploy)는 토큰을 '검증'만 한다 — 발급 호출이
노드·배선 소스에 나타나면 test_hitl의 정적 검사가 실패한다.

R1 (CONTRACT §2): 이 모듈은 verify_report를 읽지 않는다 — 실패 신호는
escalated_sections만. 인터럽트 페이로드에도 verify_report를 넣지 않는다.

토큰 설계(S6 계획 승인분): 메시지 = 배포본 마크다운 전문의 SHA-256
(approve-what-you-see — 승인 후 내용이 1바이트라도 바뀌면 검증 실패).
키 = 환경변수 SCOUTBRIEF_APPROVAL_SECRET. config.py는 §1과 문자 단위 일치가
계약이라 키 상수를 추가할 수 없고, 시크릿은 커밋되는 파일이 아니라 환경에서
온다 (.env의 OPENAI_API_KEY와 동일 관례). 재사용(replay) 방어는 MVP 범위 밖 —
단일 프로세스 데모이며, 내용 해시 바인딩으로 위조·변조는 차단된다.
"""
import hashlib
import hmac
import os
import pathlib

from langgraph.types import interrupt

import config
from src import guards

APPROVAL_SECRET_ENV = "SCOUTBRIEF_APPROVAL_SECRET"

OUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "out"
OUT_FILENAME = f"brief_{config.TEAM_OPP}_{config.TEAM_US}_{config.GAME_DATE_US}.md"

# CONTRACT §4 Tool 번호 = 각주 번호 ([T1]~[T4], 상한 4) — §7 헤더 출처 표기.
TOOL_SOURCES = [
    ("pitcher_recent", "T1", "get_pitcher_recent"),
    ("arsenal", "T2", "get_pitch_arsenal"),
    ("bvp", "T3", "get_batter_vs_pitcher"),
    ("bullpen_threats", "T4", "get_bullpen_threats"),
]

# §7 헤더의 승인 상태 표기 — 배포본은 토큰 검증을 통과한 문서이므로 승인 완료.
APPROVED_STATUS = "상태: **분석관 승인 완료** (HMAC 토큰 검증)"

# 분석관 검토 안내 — Verifier(§5)는 '숫자의 실재'만 본다. 의미 오류(방향 반전·
# 서술 요동·투구수/타수 혼동)는 이 관문에서 사람이 잡는 것이 유일한 방어선이다.
REVIEW_NOTICE = (
    "검토 안내: 수치 검증기는 숫자가 원천 데이터에 존재하는지만 확인했습니다. "
    "아래 항목은 원천 데이터(tool_results)와 육안 대조가 필요합니다 — "
    "① xwOBA 해석 방향(높을수록 타자 유리)이 서술과 일치하는가 "
    "② 같은 수치에 대한 평가가 섹션 간·문장 간 상충하지 않는가 "
    "③ 투구수(pitches)를 타수·안타로 오독한 표현이 없는가 "
    "④ escalated_sections의 플레이스홀더 섹션은 분석관 직접 작성 대상이다."
)


def deploy_markdown(tool_results: dict, draft: dict) -> str:
    """배포본 전문의 결정론 합성 — 이 문자열의 해시가 HMAC 서명 대상이다.
    hitl_gate(검증)·render_deploy(기록)·콘솔(발급)이 같은 함수로 재합성해
    바이트 일치를 보장한다 (approve-what-you-see)."""
    lines = [
        f"# {config.TEAM_OPP} @ {config.TEAM_US} 프리뷰 — 이정후 ({config.GAME_DATE_US})",
        "",
        APPROVED_STATUS,
        "",
        "출처:",
    ]
    for key, tag, name in TOOL_SOURCES:
        tr = tool_results[key]
        lines.append(f"- [{tag}] {name} — {tr['source']}, rows={tr['rows']}")
    parts = ["\n".join(lines)]
    parts.extend(draft[key] for key in config.SECTION_KEYS)
    return "\n\n---\n\n".join(parts) + "\n"


def build_interrupt_payload(state) -> dict:
    """분석관 화면 페이로드 (S6 계획 승인 범위): 배포 후보 전문 +
    escalated_sections + tool_results 원본(대조용) + 검토 안내.
    verify_report는 R1에 따라 넣지 않는다."""
    return {
        "review_notice": REVIEW_NOTICE,
        "report_md": deploy_markdown(state["tool_results"], state["draft"]),
        "escalated_sections": list(state["escalated_sections"]),
        "tool_results": state["tool_results"],
    }


def _approval_secret() -> str:
    secret = os.environ.get(APPROVAL_SECRET_ENV, "")
    if not secret:
        raise PermissionError(
            f"LLM08: 승인 키 미설정 — 환경변수 {APPROVAL_SECRET_ENV}가 필요합니다")
    return secret


def _expected_token(report_md: str, secret: str) -> str:
    digest = hashlib.sha256(report_md.encode("utf-8")).digest()
    return hmac.new(secret.encode("utf-8"), digest, hashlib.sha256).hexdigest()


def issue_approval_token(report_md: str, secret: str | None = None) -> str:
    """승인 토큰 발급 — 그래프 외부(콘솔) 전용 (CONTRACT §6 LLM08).
    그래프 노드·배선 소스에 이 함수 호출이 나타나면 test_hitl 정적 검사가 실패한다."""
    return _expected_token(report_md, secret if secret is not None else _approval_secret())


def verify_approval_token(token: str, report_md: str, secret: str | None = None) -> bool:
    """상수시간 비교 검증 — 위조(다른 키)·변조(승인 후 내용 변경) 모두 False."""
    if not token:
        return False
    expected = _expected_token(report_md, secret if secret is not None else _approval_secret())
    return hmac.compare_digest(token, expected)


def hitl_gate(state) -> dict:
    """HITL 관문 노드: interrupt로 분석관 페이로드를 내보내고, 재개 값(토큰)을
    검증해 approved에 기록한다 (CONTRACT §2:53 — approved는 이 노드만 쓴다).
    무효·부재 토큰이어도 여기서는 죽지 않는다 — 차단은 render_deploy 몫."""
    token = interrupt(build_interrupt_payload(state))
    report_md = deploy_markdown(state["tool_results"], state["draft"])
    return {"approved": bool(token) and verify_approval_token(str(token), report_md)}


def render_deploy(state) -> dict:
    """deploy 게이트 + 배포. 미승인이면 PermissionError (CONTRACT §6 LLM08 문면).
    S7: guard_output 멱등 이중방어 (CONTRACT §6:170 '제거 금지') — 정상 경로에서는
    label_pass가 이미 마스킹한 draft라 no-op이고, 따라서 승인 해시
    (approve-what-you-see)도 깨지지 않는다. label_pass를 우회한 오염 draft가
    직접 들어와도 배포본은 마스킹된다."""
    if not state["approved"]:
        raise PermissionError(
            "LLM08: 미승인 배포 차단 — 유효한 승인 토큰 없이 render_deploy에 진입했습니다")
    report_md = guards.guard_output(deploy_markdown(state["tool_results"], state["draft"]))
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / OUT_FILENAME).write_text(report_md, encoding="utf-8")
    return {"final_report": report_md}
