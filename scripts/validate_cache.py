# scripts/validate_cache.py — 캐시 5파일 스키마·불변식 검증 (S1 완료 조건)
# 검증 항목: ⓐ 5파일 존재 ⓑ 컬럼 스키마 정확 일치(순서 포함) ⓒ 파일별 불변식.
# ⑤의 COL 팀 불변식(pitching_team)은 home/away 컬럼이 ⑤ 스키마에 없어 build 시에만
# 검증 가능 (CONTRACT §3 ⑤ "build 시 불변식") — 여기서는 ⑤에서 재검증 가능한
# 불변식(기간·필수 선수 존재·도메인)을 검사한다.
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config

CACHE_DIR = pathlib.Path(__file__).resolve().parents[1] / "cache"

SCHEMAS = {
    "feltner_recent5.csv": [
        "game_date", "pitch_type", "release_speed", "pfx_x", "pfx_z",
        "description", "zone", "stand", "balls", "strikes", "on_base_any",
    ],
    "feltner_arsenal_2026.csv": [
        "stand", "count_group", "runners_group", "pitch_type", "n", "usage_pct",
        "avg_velo", "avg_pfx_x", "avg_pfx_z", "xwoba", "zone_top2",
    ],
    "bvp_lee_feltner.csv": [
        "pitch_type", "n", "xwoba", "pa_total", "ab_total", "hits_total",
    ],
    "col_bullpen_7d.csv": [
        "pitcher", "player_name", "p_throws", "appearances_7d", "pitches_7d",
        "last_game", "vsL_pitches_7d",
    ],
    "col_pitching_season.csv": [
        "game_date", "pitcher", "player_name", "p_throws", "batter", "stand",
        "pitch_type", "release_speed", "description", "events",
        "estimated_woba_using_speedangle", "inning", "at_bat_number",
        "pitch_number", "zone",
    ],
}

COUNT_GROUPS = {"ALL", "2K", "AHEAD", "BEHIND"}
RUNNERS_GROUPS = {"ALL", "ON", "EMPTY"}          # CONTRACT §3 ② (개정 2026-07-10)
HANDS = {"L", "R"}

_failures = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _failures.append(msg)


def main() -> int:
    frames = {}
    for name, cols in SCHEMAS.items():
        path = CACHE_DIR / name
        if not path.exists():
            check(False, f"{name}: 파일 없음")
            continue
        df = pd.read_csv(path)
        check(list(df.columns) == cols,
              f"{name}: 컬럼 불일치\n  기대 {cols}\n  실제 {list(df.columns)}")
        frames[name] = df

    if not _failures:
        r5 = frames["feltner_recent5.csv"]
        check(r5["game_date"].nunique() == config.RECENT_GAMES,
              f"①: 경기 수 {r5['game_date'].nunique()} != RECENT_GAMES({config.RECENT_GAMES})")
        check(set(r5["stand"]) <= HANDS, "①: stand 도메인 위반")
        check(set(r5["on_base_any"]) <= {0, 1}, "①: on_base_any 도메인 위반")

        ars = frames["feltner_arsenal_2026.csv"]
        check(len(ars) > 0, "②: 비어 있음")
        check(set(ars["count_group"]) <= COUNT_GROUPS, "②: count_group 도메인 위반")
        check(set(ars["runners_group"]) <= RUNNERS_GROUPS, "②: runners_group 도메인 위반")
        check({"ON", "EMPTY"} <= set(ars["runners_group"]),
              "②: 주자 스플릿 행(ON/EMPTY) 부재")
        check(((ars["count_group"] == "ALL") | (ars["runners_group"] == "ALL")).all(),
              "②: 축 교차 셀 존재 — 행은 count_group 또는 runners_group이 'ALL'이어야 함")
        check(set(ars["stand"]) <= HANDS, "②: stand 도메인 위반")
        for (st, cg, rg), g in ars.groupby(["stand", "count_group", "runners_group"]):
            total = g["usage_pct"].sum()
            check(abs(total - 100.0) < 0.05,
                  f"②: usage_pct 합 {total} != 100 ({st}×{cg}×{rg})")

        bvp = frames["bvp_lee_feltner.csv"]
        if len(bvp):  # 극소표본 예상 — 0행(헤더만) 허용
            for c in ("pa_total", "ab_total", "hits_total"):
                check(bvp[c].nunique() == 1, f"③: {c} 반복값 불일치")

        bp = frames["col_bullpen_7d.csv"]
        check(len(bp) > 0, "④: 비어 있음")
        check(config.FELTNER_ID not in set(bp["pitcher"]), "④: 선발(Feltner) 미제외")
        check(set(bp["p_throws"]) <= HANDS, "④: p_throws 도메인 위반")
        win_start = (pd.Timestamp(config.CACHE_END)
                     - pd.Timedelta(days=config.BULLPEN_DAYS - 1)).strftime("%Y-%m-%d")
        check(bp["last_game"].between(win_start, config.CACHE_END).all(),
              f"④: last_game이 7일 창({win_start}~{config.CACHE_END}) 밖")
        check((bp["vsL_pitches_7d"] <= bp["pitches_7d"]).all(),
              "④: vsL_pitches_7d > pitches_7d")

        season = frames["col_pitching_season.csv"]
        check(len(season) > 0, "⑤: 비어 있음")
        check(season["game_date"].between(config.SEASON_START, config.CACHE_END).all(),
              "⑤: game_date가 시즌 범위 밖")
        check(config.FELTNER_ID in set(season["pitcher"]), "⑤: Feltner 부재")
        check(config.LEE_JH_ID in set(season["batter"]), "⑤: 이정후 타석 부재")
        check(set(season["stand"].dropna()) <= HANDS, "⑤: stand 도메인 위반")
        check(set(season["p_throws"].dropna()) <= HANDS, "⑤: p_throws 도메인 위반")

        feltner_rows = int((season["pitcher"] == config.FELTNER_ID).sum())
        print(f"info: ⑤ {len(season)}행 / Feltner {feltner_rows}행 / "
              f"④ 불펜 {len(bp)}명 / ③ bvp {len(bvp)}행")

    if _failures:
        print("FAIL")
        for f in _failures:
            print(" -", f)
        return 1
    print("PASS: 캐시 5파일 스키마·불변식 검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
