import json
import pytest
from src.verifier import verify_report


# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------

def make_tool_results(**override):
    base = {
        "pitcher_recent": {"data": [{"release_speed": 94.5, "pitch_type": "FF"}], "source": "cache", "rows": 1},
        "arsenal":        {"data": [{"n": 120, "usage_pct": 55.3, "xwoba": 0.312}], "source": "cache", "rows": 1},
        "bvp":            {"data": [{"n": 4, "xwoba": 0.250, "pa_total": 3}], "source": "cache", "rows": 1},
        "bullpen_threats": {"data": [{"threat_score": 6, "vsL_xwoba": 0.285}], "source": "cache", "rows": 1},
    }
    base.update(override)
    return base


# ---------------------------------------------------------------------------
# 케이스 1: 정상 통과 — draft 숫자가 tool_results에 존재
# ---------------------------------------------------------------------------

def test_normal_pass():
    tool_results = make_tool_results()
    # 94.5 는 tool_results 안에 있다
    draft = {"feltner": "패스트볼 평균 구속 94.5mph.", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True
    assert report["feltner"]["mismatches"] == []


# ---------------------------------------------------------------------------
# 케이스 2: 오염 검출 — tool_results에 없는 숫자
# ---------------------------------------------------------------------------

def test_contamination_detected():
    tool_results = make_tool_results()
    # 99.9 는 어디에도 없다
    draft = {"feltner": "평균 구속 99.9mph.", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is False
    assert len(report["feltner"]["mismatches"]) > 0


# ---------------------------------------------------------------------------
# 케이스 3: [T3] 각주 무시
# ---------------------------------------------------------------------------

def test_footnote_tag_ignored():
    tool_results = make_tool_results()
    # [T3] 안의 숫자 3 은 소거 후 검사 대상에서 제외
    draft = {"feltner": "구종 분포를 참고하라. [T3] 캐시 기준.", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True


# ---------------------------------------------------------------------------
# 케이스 4: 날짜 무시 (YYYY-MM-DD 형식)
# ---------------------------------------------------------------------------

def test_date_ignored():
    tool_results = make_tool_results()
    # 2026-07-09 날짜는 소거 후 검사 대상에서 제외
    draft = {"feltner": "기준일 2026-07-09 기록.", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True


# ---------------------------------------------------------------------------
# 케이스 5: 정책 상수 허용 (POLICY_CONSTANTS)
# ---------------------------------------------------------------------------

def test_policy_constant_allowed():
    tool_results = make_tool_results()
    # "20"은 POLICY_CONSTANTS에 있으므로 tool_results에 없어도 통과
    draft = {"feltner": "", "matchup": "소표본 기준 20 PA 미만.", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["matchup"]["pass"] is True


# ---------------------------------------------------------------------------
# 케이스 6: "2스트라이크" — 접미사 소거로 숫자 무시
# ---------------------------------------------------------------------------

def test_strike_suffix_ignored():
    tool_results = make_tool_results()
    # "2스트라이크" → 층1 소거 → "2"가 남지 않아야 한다 (또는 소거된 채 검사)
    draft = {"feltner": "2스트라이크 카운트에서 슬라이더 비중 증가.", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True


# ---------------------------------------------------------------------------
# 추가: 슬래시 날짜 무시 (7/9 형식)
# ---------------------------------------------------------------------------

def test_slash_date_ignored():
    tool_results = make_tool_results()
    draft = {"feltner": "7/9 경기 선발.", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True


# ---------------------------------------------------------------------------
# 추가: 연도 무시 (20XX)
# ---------------------------------------------------------------------------

def test_year_ignored():
    tool_results = make_tool_results()
    draft = {"feltner": "2026 시즌 기준.", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True


# ---------------------------------------------------------------------------
# 추가: 여러 섹션 혼합 — 일부만 실패
# ---------------------------------------------------------------------------

def test_partial_failure():
    tool_results = make_tool_results()
    draft = {
        "feltner":  "구속 94.5mph.",    # tool_results에 있음 → pass
        "matchup":  "타율 .999.",        # 없음 → fail  (소수점 포함 숫자)
        "bullpen":  "",
        "gameplan": "",
    }
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True
    assert report["matchup"]["pass"] is False


# ---------------------------------------------------------------------------
# 추가: 마크다운 헤더 번호 무시
# ---------------------------------------------------------------------------

def test_header_number_ignored():
    tool_results = make_tool_results()
    draft = {"feltner": "## 1. 선발 투수 분석\n구속 94.5mph.", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True


# ---------------------------------------------------------------------------
# [레드팀] 우회 케이스 — corpus 부분 일치 / 층1 소거 맹점
# ---------------------------------------------------------------------------

def test_redteam_corpus_partial_int_in_float_speed():
    # 정수 94는 corpus에 없다 (corpus_numbers = {"94.5", ...}). 올바르게 차단.
    tool_results = make_tool_results()
    draft = {"feltner": "구속 94mph", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is False


def test_redteam_corpus_partial_int_embedded_in_xwoba():
    # 정수 12는 corpus_numbers에 없다 (있는 건 "0.312"). 올바르게 차단.
    tool_results = make_tool_results()
    draft = {"feltner": "12개 투구 기록", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is False


def test_redteam_corpus_partial_int_embedded_in_vsL_xwoba():
    # 정수 28은 corpus_numbers에 없다 (있는 건 "0.285"). 올바르게 차단.
    tool_results = make_tool_results()
    draft = {"feltner": "위협지수 28", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is False


def test_redteam_corpus_partial_int_in_bvp_xwoba():
    # 정수 25는 corpus_numbers에 없다 (0.250 → json 직렬화 "0.25"). 올바르게 차단.
    tool_results = make_tool_results()
    draft = {"feltner": "타율 25위", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is False


def test_redteam_double_digit_suffix_ball_leaks_prefix():
    # BUG: 층1 접미소거 패턴 \d(?=볼)은 볼 바로 앞 한 자리만 소거.
    # "12볼" → "1볼" → 정규화 후 "1"이 추출됨. "1"은 corpus의 "rows": 1에 포함되어 통과.
    # 의미 단위 "12볼"이 두 자리 앞부분 "1"로 둔갑하여 우회.
    tool_results = make_tool_results()
    draft = {"feltner": "12볼 카운트 상황", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True  # 현재 동작: 통과 (버그)


def test_redteam_double_digit_suffix_inning_leaks_prefix():
    # BUG: 층1 접미소거 패턴 \d(?=회)은 회 바로 앞 한 자리만 소거.
    # "10회" → "1회" → 정규화 후 "1"이 추출됨. "1"은 corpus의 "rows": 1에 포함되어 통과.
    # 연장전 10회가 1회로 둔갑하여 우회.
    tool_results = make_tool_results()
    draft = {"feltner": "10회 연장전 출전", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True  # 현재 동작: 통과 (버그)


def test_redteam_source_meta_date_token_leaks_into_corpus():
    # BUG: tool_results의 source 필드("statcast(cache:07-08 14:30)")가 corpus JSON 직렬화에 포함됨.
    # "14:30" 안의 정수 14가 corpus 부분 문자열로 존재하여, draft의 조작된 "14경기" 수치가 통과.
    # source 메타 타임스탬프가 층2 화이트리스트로 오작동.
    tool_results = make_tool_results(
        pitcher_recent={"data": [{"release_speed": 94.5}], "source": "statcast(cache:07-08 14:30)", "rows": 1}
    )
    draft = {"feltner": "14경기 등판 기록", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True  # 현재 동작: 통과 (버그)


def test_redteam_undefined_footnote_T5_bypasses_via_policy_constant():
    # BUG: CONTRACT §5 소거 대상은 [T1]~[T4]뿐, [T5] 이상은 소거되지 않음.
    # [T5] 태그가 소거되지 않아 "5"가 추출되지만, "5"는 POLICY_CONSTANTS에 포함되어 통과.
    # 정의되지 않은 각주 번호 [T5]가 층1 소거 맹점 + 층2 POLICY_CONSTANTS 중복으로 우회.
    tool_results = make_tool_results()
    draft = {"feltner": "[T5] 항목 참조", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True  # 현재 동작: 통과 (버그)


def test_redteam_fraction_slash_korean_boundary_not_stripped():
    # BUG: 층1 슬래시날짜 소거 패턴 \b\d{1,2}/\d{1,2}\b 에서 \b(워드바운더리)는 한국어 직전에 적용 안됨.
    # "3/4이닝"은 '이닝' 앞에 \b가 실패하여 소거되지 않고, 3과 4가 그대로 추출됨.
    # 단, 3은 bvp pa_total:3, 4는 bvp n:4를 통해 corpus 부분 일치로 추가 통과.
    # 슬래시 분수 표현이 한국어 접미사와 직접 결합 시 층1 소거 + 층2 복합 우회.
    tool_results = make_tool_results()
    draft = {"feltner": "3/4이닝 투구", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is True  # 현재 동작: 통과 (버그)


def test_redteam_float_precision_impute_value_blocked():
    # 정상 차단 케이스: config.VSL_XWOBA_IMPUTE = 0.320 이지만 json.dumps는 후행 0을 제거하여 0.32로 직렬화.
    # 따라서 draft에 "0.320"을 쓰면 corpus의 "0.32"와 불일치하여 Verifier가 올바르게 차단함.
    # (의도치 않은 차단 가능성: LLM이 원본 상수값 0.320을 draft에 그대로 인용하면 오탐)
    tool_results = make_tool_results(
        arsenal={"data": [{"n": 120, "usage_pct": 55.3, "xwoba": 0.320}], "source": "cache", "rows": 1}
    )
    draft = {"feltner": "vsL xwOBA 0.320", "matchup": "", "bullpen": "", "gameplan": ""}
    report = verify_report(draft, tool_results)
    assert report["feltner"]["pass"] is False  # 현재 동작: 차단 (0.320 != 0.32)
