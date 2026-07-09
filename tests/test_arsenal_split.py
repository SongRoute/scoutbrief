"""
test_arsenal_split.py — §3 ② runners_group 축 (exp/allin-runner-split P3).
build_arsenal의 축 규약·ON 분류·usage_pct 합, Tool 2 행 스키마(실캐시·오프라인),
feltner 지시문의 스플릿 지시. 판정은 pytest가 한다 (CLAUDE.md 규칙 11).
"""
import pandas as pd

import config
from scripts.build_cache import build_arsenal, runners_group_masks
from src.graph import SECTION_SPECS
from src.mcp_server import get_pitch_arsenal

ARSENAL_COLS = [  # CONTRACT §3 ② 컬럼 순서
    "stand", "count_group", "runners_group", "pitch_type", "n", "usage_pct",
    "avg_velo", "avg_pfx_x", "avg_pfx_z", "xwoba", "zone_top2",
]


def _raw(rows):
    """build_arsenal 입력 형태의 최소 합성 원시 프레임."""
    base = {
        "stand": "L", "pitch_type": "FF", "release_speed": 94.0,
        "pfx_x": 0.5, "pfx_z": 1.2, "estimated_woba_using_speedangle": None,
        "zone": 5, "balls": 0, "strikes": 0,
        "on_1b": None, "on_2b": None, "on_3b": None,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def test_runners_group_masks_on_when_any_base_occupied():
    df = _raw([
        {"on_1b": 111.0},                      # 1루만 → ON
        {"on_3b": 222.0},                      # 3루만 → ON
        {},                                    # 전부 null → EMPTY
    ])
    masks = runners_group_masks(df)
    assert masks["ON"].tolist() == [True, True, False]
    assert masks["EMPTY"].tolist() == [False, False, True]


def test_build_arsenal_axis_rule_and_columns():
    df = _raw([
        {"on_1b": 111.0}, {"on_1b": 111.0, "pitch_type": "SL"},
        {}, {"pitch_type": "SL"}, {"strikes": 2},
    ])
    ars = build_arsenal(df)
    assert list(ars.columns) == ARSENAL_COLS
    # 축 규약: 어느 한 축은 'ALL' — 교차 셀 없음
    assert ((ars["count_group"] == "ALL") | (ars["runners_group"] == "ALL")).all()
    assert {"ON", "EMPTY"} <= set(ars["runners_group"])
    # 기존 count_group 스플릿 행은 전부 runners_group=='ALL'
    assert (ars.loc[ars["count_group"] != "ALL", "runners_group"] == "ALL").all()


def test_build_arsenal_usage_sums_100_per_cell_group():
    df = _raw([
        {"on_1b": 111.0}, {"on_1b": 111.0, "pitch_type": "SL"}, {"on_2b": 1.0},
        {}, {"pitch_type": "SL"}, {"pitch_type": "CH"},
    ])
    ars = build_arsenal(df)
    for _, g in ars.groupby(["stand", "count_group", "runners_group"]):
        assert abs(g["usage_pct"].sum() - 100.0) < 0.05


def test_tool2_rows_carry_runners_group_offline():
    """실캐시 경로 (읽기 전용·오프라인) — §4 Tool 2 행 스키마."""
    res = get_pitch_arsenal(config.FELTNER_ID)
    assert res["rows"] > 0
    for row in res["data"]:
        assert set(ARSENAL_COLS) <= set(row)
        assert row["runners_group"] in {"ALL", "ON", "EMPTY"}
        assert row["count_group"] == "ALL" or row["runners_group"] == "ALL"
    assert {"ON", "EMPTY"} <= {r["runners_group"] for r in res["data"]}


def test_feltner_instructions_cover_runner_split_without_interpretation():
    """지시문 최소 고정: 스플릿 축 언급 + 수치 비교 한정 + 해석 금지 문구.
    산문 전문 고정은 취약하므로 키워드 수준만 고정한다."""
    text = SECTION_SPECS["feltner"]["instructions"]
    assert "runners_group" in text
    assert "'ON'" in text and "'EMPTY'" in text
    assert "usage_pct" in text
    assert "해석하지 않는다" in text
    assert "pitches 값을 병기" in text
