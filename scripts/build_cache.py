# scripts/build_cache.py — 캐시 5파일 생성 (CONTRACT.md §3)
# - 반올림은 이 파일에서만 수행한다 (CLAUDE.md 규칙 3).
# - cache/*.csv 재생성은 이 스크립트로만 (규칙 2).
# - 공통 필터: game_type=='R' (시범경기 제외).
# - xwoba 집계 규약: estimated_woba_using_speedangle 비결측 행의 평균, float(3).
#   비결측 행이 없으면 결측(nullable) 유지.
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config

CACHE_DIR = pathlib.Path(__file__).resolve().parents[1] / "cache"

# 통계 정의용 도메인 상수 (정책 아님 — MLB 이벤트 어휘)
HIT_EVENTS = {"single", "double", "triple", "home_run"}
NON_AB_EVENTS = {
    "walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt",
    "catcher_interf", "sac_fly_double_play", "sac_bunt_double_play",
    "truncated_pa",
}

# ⑤ 출력 컬럼 (CONTRACT §3 ⑤ — 유일하게 비반올림 원시 데이터)
SEASON_COLS = [
    "game_date", "pitcher", "player_name", "p_throws", "batter", "stand",
    "pitch_type", "release_speed", "description", "events",
    "estimated_woba_using_speedangle", "inning", "at_bat_number",
    "pitch_number", "zone",
]


def fetch_season_raw() -> pd.DataFrame:
    """시즌 COL 투구 원시 풀. 내부 파생용 컬럼(game_pk, balls 등) 포함."""
    from pybaseball import statcast

    df = statcast(
        start_dt=config.SEASON_START, end_dt=config.CACHE_END,
        team=config.TEAM_OPP, verbose=False,
    )
    df = df[df["game_type"] == "R"].copy()
    df["game_date"] = df["game_date"].astype(str).str[:10]

    # build 시 불변식 (버전 드리프트 감지선 — 제거 금지, CONTRACT §3 ⑤)
    df["pitching_team"] = np.where(df.inning_topbot == "Top", df.home_team, df.away_team)
    assert (df["pitching_team"] == config.TEAM_OPP).all(), \
        "pybaseball team= 필터 의미 변경 — 버전 드리프트"

    return df.sort_values(["game_date", "game_pk", "at_bat_number", "pitch_number"])


def count_group_masks(df: pd.DataFrame) -> dict:
    """count_group 라벨 정의 (CONTRACT §3 ② — 투수 기준). 그룹은 중첩 허용."""
    return {
        "ALL": pd.Series(True, index=df.index),
        "2K": df["strikes"] == 2,          # '2K' = 2스트라이크: 라벨 자체가 정의
        "AHEAD": df["strikes"] > df["balls"],
        "BEHIND": df["balls"] > df["strikes"],
    }


def runners_group_masks(df: pd.DataFrame) -> dict:
    """runners_group 라벨 정의 (CONTRACT §3 ②) —
    ON = 투구 시점 on_1b/on_2b/on_3b 중 하나라도 non-null, EMPTY = 전부 null."""
    on = df[["on_1b", "on_2b", "on_3b"]].notna().any(axis=1)
    return {"ON": on, "EMPTY": ~on}


def pct_largest_remainder(counts: pd.Series) -> pd.Series:
    """float(1) usage_pct — largest remainder로 그룹 내 합을 정확히 100.0으로 맞춘다."""
    raw = counts / counts.sum() * 100 * 10          # 0.1%p 단위 정수 배분
    base = np.floor(raw).astype(int)
    shortfall = int(100 * 10 - base.sum())
    for idx in (raw - base).sort_values(ascending=False).index[:shortfall]:
        base[idx] += 1
    return base / 10.0


def zone_top2(zones: pd.Series) -> str:
    """빈도 상위 2개 존. 동률은 존 번호 오름차순 — 결정론."""
    vc = zones.dropna().astype(int).value_counts().rename_axis("zone").reset_index(name="cnt")
    vc = vc.sort_values(["cnt", "zone"], ascending=[False, True])
    return ",".join(str(z) for z in vc["zone"].head(2))


def build_recent5(feltner: pd.DataFrame) -> pd.DataFrame:
    """① feltner_recent5.csv — 최근 RECENT_GAMES경기 투구 단위."""
    games = (feltner[["game_date", "game_pk"]].drop_duplicates()
             .sort_values(["game_date", "game_pk"]))
    recent = set(games.tail(config.RECENT_GAMES)["game_pk"])
    df = feltner[feltner["game_pk"].isin(recent)]
    return pd.DataFrame({
        "game_date": df["game_date"],
        "pitch_type": df["pitch_type"],
        "release_speed": df["release_speed"].round(1),
        "pfx_x": df["pfx_x"].round(2),
        "pfx_z": df["pfx_z"].round(2),
        "description": df["description"],
        "zone": df["zone"].astype("Int64"),
        "stand": df["stand"],
        "balls": df["balls"].astype(int),
        "strikes": df["strikes"].astype(int),
        "on_base_any": (df["on_1b"].notna() | df["on_2b"].notna()
                        | df["on_3b"].notna()).astype(int),
    })


def build_arsenal(feltner: pd.DataFrame) -> pd.DataFrame:
    """② feltner_arsenal_2026.csv — stand × (count_group | runners_group) × pitch_type 1행.
    축 규약 (CONTRACT §3 ②): 두 스플릿 축은 교차하지 않는다 — 셀 목록이
    count_group×(runners='ALL')와 runners×(count='ALL')의 합집합이라 교차 셀은
    구조적으로 생성되지 않는다. count_group_masks의 'ALL'이 기본 아스널
    (ALL×ALL) 행을 만들므로 runners 쪽 'ALL'은 별도 셀로 두지 않는다."""
    rows = []
    for stand in ("L", "R"):
        sub = feltner[feltner["stand"] == stand]
        if sub.empty:
            continue
        cells = [(cg, "ALL", mask) for cg, mask in count_group_masks(sub).items()]
        cells += [("ALL", rg, mask) for rg, mask in runners_group_masks(sub).items()]
        for cg, rg, mask in cells:
            g = sub[mask]
            if g.empty:
                continue
            counts = g.groupby("pitch_type").size().sort_index()
            pcts = pct_largest_remainder(counts)
            for pt in counts.index:
                gp = g[g["pitch_type"] == pt]
                xw = gp["estimated_woba_using_speedangle"].dropna()
                rows.append({
                    "stand": stand, "count_group": cg, "runners_group": rg,
                    "pitch_type": pt,
                    "n": int(counts[pt]),
                    "usage_pct": pcts[pt],
                    "avg_velo": round(gp["release_speed"].mean(), 1),
                    "avg_pfx_x": round(gp["pfx_x"].mean(), 2),
                    "avg_pfx_z": round(gp["pfx_z"].mean(), 2),
                    "xwoba": round(xw.mean(), 3) if len(xw) else None,
                    "zone_top2": zone_top2(gp["zone"]),
                })
    return pd.DataFrame(rows)


def build_bvp(season: pd.DataFrame) -> pd.DataFrame:
    """③ bvp_lee_feltner.csv — 구종별 1행, 통산 합계는 반복 컬럼."""
    bvp = season[(season["batter"] == config.LEE_JH_ID)
                 & (season["pitcher"] == config.FELTNER_ID)]
    cols = ["pitch_type", "n", "xwoba", "pa_total", "ab_total", "hits_total"]
    if bvp.empty:
        return pd.DataFrame(columns=cols)
    pa_rows = bvp[bvp["events"].notna()]
    pa_total = pa_rows[["game_pk", "at_bat_number"]].drop_duplicates().shape[0]
    ab_total = int((~pa_rows["events"].isin(NON_AB_EVENTS)).sum())
    hits_total = int(pa_rows["events"].isin(HIT_EVENTS).sum())
    rows = []
    for pt, gp in bvp.groupby("pitch_type"):
        xw = gp["estimated_woba_using_speedangle"].dropna()
        rows.append({
            "pitch_type": pt, "n": len(gp),
            "xwoba": round(xw.mean(), 3) if len(xw) else None,
            "pa_total": pa_total, "ab_total": ab_total, "hits_total": hits_total,
        })
    return pd.DataFrame(rows, columns=cols)


def build_bullpen_7d(season: pd.DataFrame) -> pd.DataFrame:
    """④ col_bullpen_7d.csv — 7일 풀에서 선발 제외, 투수당 1행.

    선발 판정: '경기 첫 투수 = 선발' 휴리스틱 (CLAUDE.md 알려진 리스크 — 수용됨.
    등판 메타를 원문 노출하고 분석관이 육안 필터).
    """
    end = pd.Timestamp(config.CACHE_END)
    start = (end - pd.Timedelta(days=config.BULLPEN_DAYS - 1)).strftime("%Y-%m-%d")
    win = season[(season["game_date"] >= start)
                 & (season["game_date"] <= config.CACHE_END)]
    firsts = (win.sort_values(["game_pk", "at_bat_number", "pitch_number"])
              .groupby("game_pk").first())
    starters = set(firsts["pitcher"])
    pool = win[~win["pitcher"].isin(starters)]
    rows = []
    for pid, gp in pool.groupby("pitcher"):
        rows.append({
            "pitcher": int(pid),
            "player_name": gp["player_name"].iloc[0],
            "p_throws": gp["p_throws"].iloc[0],
            "appearances_7d": gp["game_pk"].nunique(),
            "pitches_7d": len(gp),
            "last_game": gp["game_date"].max(),
            "vsL_pitches_7d": int((gp["stand"] == "L").sum()),
        })
    return pd.DataFrame(rows).sort_values("pitcher")


def main() -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    print(f"statcast 조회: {config.TEAM_OPP} {config.SEASON_START}~{config.CACHE_END} …")
    season = fetch_season_raw()
    print(f"  시즌 풀 {len(season)}행 (game_type=='R')")

    feltner = season[season["pitcher"] == config.FELTNER_ID]
    feltner_games = feltner["game_pk"].nunique()
    print(f"  Feltner {len(feltner)}행 / {feltner_games}경기")

    outputs = {
        "feltner_recent5.csv": build_recent5(feltner),
        "feltner_arsenal_2026.csv": build_arsenal(feltner),
        "bvp_lee_feltner.csv": build_bvp(season),
        "col_bullpen_7d.csv": build_bullpen_7d(season),
        "col_pitching_season.csv": season[SEASON_COLS],
    }
    for name, df in outputs.items():
        path = CACHE_DIR / name
        df.to_csv(path, index=False)
        print(f"  wrote {path.name}: {len(df)}행")


if __name__ == "__main__":
    main()
