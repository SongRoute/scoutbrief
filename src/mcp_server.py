# src/mcp_server.py — MCP 서버 4 Tool (CONTRACT.md §4, 상한 4·추가 금지)
# - 공통 반환 래퍼: {"data": [...], "source": "statcast(cache:MM-DD HH:MM)"|"statcast(live)", "rows": int}
# - 캐시 우선. live 경로는 옵션: 환경변수 SCOUTBRIEF_LIVE=1일 때만 시도,
#   실패 시 캐시로 fallback (발표일 기본은 캐시 — SESSIONS.md S2).
# - 반올림 금지(CLAUDE.md 규칙 3). 예외: CONTRACT §4에 float(3)이 명시된
#   Tool 4의 vsL_xwoba·bvp_xwoba만 이 파일에서 round(x, 3) 수행.
# - threat_score·availability는 결정론적 코드 — LLM 호출 금지(규칙 4).
import os
import pathlib
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config

from mcp.server.fastmcp import FastMCP

CACHE_DIR = pathlib.Path(__file__).resolve().parents[1] / "cache"
RECENT5_CSV = CACHE_DIR / "feltner_recent5.csv"          # 캐시 ①
ARSENAL_CSV = CACHE_DIR / "feltner_arsenal_2026.csv"     # 캐시 ②
BVP_CSV = CACHE_DIR / "bvp_lee_feltner.csv"              # 캐시 ③
BULLPEN_CSV = CACHE_DIR / "col_bullpen_7d.csv"           # 캐시 ④
SEASON_CSV = CACHE_DIR / "col_pitching_season.csv"       # 캐시 ⑤

LIVE_ENV = "SCOUTBRIEF_LIVE"                             # "1"일 때만 live 시도
CACHE_SEASON = int(config.SEASON_START[:4])              # 캐시가 커버하는 시즌

mcp_app = FastMCP("scoutbrief")

_frames: dict = {}                                       # 캐시 CSV 메모(읽기 전용)


def _load(path: pathlib.Path) -> pd.DataFrame:
    if path.name not in _frames:
        dtype = {"zone": "Int64"} if path == RECENT5_CSV else None
        _frames[path.name] = pd.read_csv(path, dtype=dtype)
    return _frames[path.name]


def _cache_source(*paths: pathlib.Path) -> str:
    ts = max(p.stat().st_mtime for p in paths)
    return f"statcast(cache:{datetime.fromtimestamp(ts).strftime('%m-%d %H:%M')})"


def _records(df: pd.DataFrame) -> list[dict]:
    """JSON 직렬화 가능한 레코드 목록 (numpy 타입 → python, 결측 → None)."""
    out = []
    for rec in df.to_dict(orient="records"):
        row = {}
        for k, v in rec.items():
            if v is None or (pd.api.types.is_scalar(v) and pd.isna(v)):
                row[k] = None
            elif isinstance(v, np.integer):
                row[k] = int(v)
            elif isinstance(v, np.floating):
                row[k] = float(v)
            else:
                row[k] = v
        out.append(row)
    return out


def _wrap(data: list[dict], source: str) -> dict:
    return {"data": data, "source": source, "rows": len(data)}


def _live_enabled() -> bool:
    return os.environ.get(LIVE_ENV) == "1"


def _live_season_raw() -> pd.DataFrame:
    """live 원시 풀 — 조회·불변식은 build_cache 소유 코드를 재사용(단일 출처)."""
    from scripts.build_cache import fetch_season_raw
    return fetch_season_raw()


# ── Tool 1 ─────────────────────────────────────────────────────────────────
@mcp_app.tool()
def get_pitcher_recent(pitcher_id: int, n_games: int = config.RECENT_GAMES) -> dict:
    """최근 n_games경기 투구 단위 데이터 (캐시 ①)."""
    if not 1 <= n_games <= config.RECENT_GAMES:
        raise ValueError(f"n_games는 1~{config.RECENT_GAMES} (캐시 ① 보유 범위)")
    if _live_enabled():
        try:
            from scripts.build_cache import build_recent5
            raw = _live_season_raw()
            df = build_recent5(raw[raw["pitcher"] == pitcher_id])
            return _wrap(_records(_tail_games(df, n_games)), "statcast(live)")
        except Exception:
            pass
    if pitcher_id != config.FELTNER_ID:
        raise ValueError(f"캐시 ①은 pitcher_id={config.FELTNER_ID}만 보유")
    df = _load(RECENT5_CSV)
    return _wrap(_records(_tail_games(df, n_games)), _cache_source(RECENT5_CSV))


def _tail_games(df: pd.DataFrame, n_games: int) -> pd.DataFrame:
    dates = sorted(df["game_date"].unique())[-n_games:]
    return df[df["game_date"].isin(dates)]


# ── Tool 2 ─────────────────────────────────────────────────────────────────
@mcp_app.tool()
def get_pitch_arsenal(pitcher_id: int, season: int = 2026) -> dict:
    """stand × count_group × pitch_type 아스널 (캐시 ②)."""
    if season != CACHE_SEASON:
        raise ValueError(f"캐시 ②는 {CACHE_SEASON} 시즌만 보유")
    if _live_enabled():
        try:
            from scripts.build_cache import build_arsenal
            raw = _live_season_raw()
            df = build_arsenal(raw[raw["pitcher"] == pitcher_id])
            return _wrap(_records(df), "statcast(live)")
        except Exception:
            pass
    if pitcher_id != config.FELTNER_ID:
        raise ValueError(f"캐시 ②는 pitcher_id={config.FELTNER_ID}만 보유")
    df = _load(ARSENAL_CSV)
    return _wrap(_records(df), _cache_source(ARSENAL_CSV))


# ── Tool 3 ─────────────────────────────────────────────────────────────────
@mcp_app.tool()
def get_batter_vs_pitcher(batter_id: int, pitcher_id: int) -> dict:
    """선발 상대 개인 전적, 구종별 (캐시 ③). 불펜 개인 전적은 Tool 4가 흡수."""
    if (batter_id, pitcher_id) != (config.LEE_JH_ID, config.FELTNER_ID):
        raise ValueError(
            f"캐시 ③은 (batter={config.LEE_JH_ID}, pitcher={config.FELTNER_ID})만 보유")
    if _live_enabled():
        try:
            from scripts.build_cache import build_bvp
            df = build_bvp(_live_season_raw())
            return _wrap(_records(df), "statcast(live)")
        except Exception:
            pass
    df = _load(BVP_CSV)
    return _wrap(_records(df), _cache_source(BVP_CSV))


# ── Tool 4 ─────────────────────────────────────────────────────────────────
@mcp_app.tool()
def get_bullpen_threats(team: str, batter_id: int,
                        days_usage: int = config.BULLPEN_DAYS) -> dict:
    """7일 풀 전원(컷오프 없음), threat_score 내림차순 (캐시 ④+⑤, CONTRACT §4)."""
    if team != config.TEAM_OPP:
        raise ValueError(f"캐시 ④⑤는 team={config.TEAM_OPP}만 보유")
    if days_usage != config.BULLPEN_DAYS:
        raise ValueError(f"캐시 ④는 days_usage={config.BULLPEN_DAYS} 고정")
    if _live_enabled():
        try:
            from scripts.build_cache import SEASON_COLS, build_bullpen_7d
            raw = _live_season_raw()
            rows = _bullpen_threat_rows(build_bullpen_7d(raw), raw[SEASON_COLS], batter_id)
            return _wrap(rows, "statcast(live)")
        except Exception:
            pass
    rows = _bullpen_threat_rows(_load(BULLPEN_CSV), _load(SEASON_CSV), batter_id)
    return _wrap(rows, _cache_source(BULLPEN_CSV, SEASON_CSV))


def _bullpen_threat_rows(bullpen: pd.DataFrame, season: pd.DataFrame,
                         batter_id: int) -> list[dict]:
    """CONTRACT §4 Tool 4 행 스키마 + threat_score 결정론 계산 (LLM 금지)."""
    vsl = season[season["stand"] == "L"]
    game_date = pd.Timestamp(config.GAME_DATE_US)
    rows = []
    for r in bullpen.itertuples():
        pv = vsl[vsl["pitcher"] == r.pitcher]
        xw = pv["estimated_woba_using_speedangle"].dropna()
        # CONTRACT §4 float(3) 명시 필드 — 규칙 3 예외로 Tool 내부 반올림
        vsl_xwoba = round(float(xw.mean()), 3) if len(xw) else None
        # 결측 시 VSL_XWOBA_IMPUTE는 순위 계산에만 대입(config 주석: 리포트 인용
        # 절대 금지). 반환 필드는 None 유지 — 대입값이 tool_results에 실리면
        # Verifier가 그 인용을 통과시켜 방어선이 무너진다.
        rest_days = (game_date - pd.Timestamp(r.last_game)).days
        rows.append({
            "pitcher_id": int(r.pitcher),
            "name": r.player_name,
            "throws": r.p_throws,
            "appearances_7d": int(r.appearances_7d),
            "pitches_7d": int(r.pitches_7d),
            "last_game": r.last_game,
            "rest_days": rest_days,
            "vsL_xwoba": vsl_xwoba,
            "vsL_top2_usage": _top2_usage(pv),
            "vsL_low_n": 1 if (len(pv) < config.VSL_LOW_N_PITCHES or vsl_xwoba is None) else 0,
            **_bvp_fields(season, batter_id, int(r.pitcher)),
            "availability": config.availability(
                rest_days, int(r.pitches_7d), int(r.appearances_7d)),
            "_vsl_n": len(pv),                       # 동률 판정용 내부 필드(출력 전 제거)
        })
    # suppression_weight = N+1 − rank(vsL_xwoba 오름차순). 낮을수록 위협 = 큰 가중치.
    # 동률: vsL 투구수 많은 쪽 우선. 최종 동률은 pitcher_id 오름차순(결정론 보장).
    n = len(rows)
    ranked = sorted(rows, key=lambda x: (
        x["vsL_xwoba"] if x["vsL_xwoba"] is not None else config.VSL_XWOBA_IMPUTE,
        -x["_vsl_n"], x["pitcher_id"]))
    for rank, row in enumerate(ranked, start=1):
        row["threat_score"] = row["availability"] * (n + 1 - rank)
        row["lefty_flag"] = 1 if row["throws"] == "L" else 0
    rows.sort(key=lambda x: (-x["threat_score"], -x["_vsl_n"], x["pitcher_id"]))
    for row in rows:
        del row["_vsl_n"]
    return rows


def _top2_usage(pv: pd.DataFrame) -> str:
    """vsL 사용률 상위 2개 구종명 쉼표 연결 (캐시 ② zone_top2 관례).
    동률: 투구수 내림차순 → 구종명 오름차순 (CONTRACT §4)."""
    counts = pv.groupby("pitch_type").size()
    top2 = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    return ",".join(pt for pt, _ in top2)


def _bvp_fields(season: pd.DataFrame, batter_id: int, pitcher_id: int) -> dict:
    bvp = season[(season["batter"] == batter_id) & (season["pitcher"] == pitcher_id)]
    xw = bvp["estimated_woba_using_speedangle"].dropna()
    return {
        "bvp_pa": int(bvp["events"].notna().sum()),
        # CONTRACT §4 float(3) 명시 필드 — 규칙 3 예외로 Tool 내부 반올림
        "bvp_xwoba": round(float(xw.mean()), 3) if len(xw) else None,
    }


if __name__ == "__main__":
    mcp_app.run()
