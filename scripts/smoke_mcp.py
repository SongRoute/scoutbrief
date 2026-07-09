# scripts/smoke_mcp.py — MCP 4 Tool 스모크 (SESSIONS.md S2 완료 조건)
# 1패스: 4 Tool 호출 → JSON 직렬화 + source·rows 존재 확인.
# 2패스: 소켓 차단 + 모듈 재적재 후 재실행 — 캐시 경로가 네트워크 없이 동작함을 증명.
import importlib
import json
import pathlib
import socket
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config

REQUIRED_KEYS = ("data", "source", "rows")
# CONTRACT §3 ② = §4 Tool 2 행 스키마 (개정 2026-07-10: runners_group 포함)
TOOL2_FIELDS = (
    "stand", "count_group", "runners_group", "pitch_type", "n", "usage_pct",
    "avg_velo", "avg_pfx_x", "avg_pfx_z", "xwoba", "zone_top2",
)
TOOL4_FIELDS = (
    "pitcher_id", "name", "throws", "appearances_7d", "pitches_7d", "last_game",
    "rest_days", "vsL_xwoba", "vsL_top2_usage", "vsL_low_n", "bvp_pa", "bvp_xwoba",
    "availability", "threat_score", "lefty_flag",
)


def run_all(tag: str) -> None:
    srv = importlib.import_module("src.mcp_server")
    results = {
        "get_pitcher_recent": srv.get_pitcher_recent(config.FELTNER_ID),
        "get_pitch_arsenal": srv.get_pitch_arsenal(config.FELTNER_ID),
        "get_batter_vs_pitcher": srv.get_batter_vs_pitcher(
            config.LEE_JH_ID, config.FELTNER_ID),
        "get_bullpen_threats": srv.get_bullpen_threats(
            config.TEAM_OPP, config.LEE_JH_ID),
    }
    for name, res in results.items():
        json.dumps(res, ensure_ascii=False)  # JSON 직렬화 가능해야 한다 (R2 전제)
        for key in REQUIRED_KEYS:
            assert key in res, f"{name}: '{key}' 누락"
        assert isinstance(res["rows"], int) and res["rows"] == len(res["data"]), \
            f"{name}: rows != len(data)"
        assert res["rows"] > 0, f"{name}: 빈 데이터"
        assert res["source"].startswith("statcast("), f"{name}: source 형식 위반"
        print(f"  [{tag}] {name}: rows={res['rows']} source={res['source']}")

    arsenal = results["get_pitch_arsenal"]["data"]
    for row in arsenal:
        missing = [f for f in TOOL2_FIELDS if f not in row]
        assert not missing, f"Tool2 필드 누락: {missing}"
        assert row["count_group"] == "ALL" or row["runners_group"] == "ALL", \
            "Tool2: 축 교차 셀 (§3 ② 축 규약 위반)"
    rgs = {row["runners_group"] for row in arsenal}
    assert {"ON", "EMPTY"} <= rgs, f"Tool2: 주자 스플릿 행 부재 (관측: {rgs})"

    threats = results["get_bullpen_threats"]["data"]
    for row in threats:
        missing = [f for f in TOOL4_FIELDS if f not in row]
        assert not missing, f"Tool4 필드 누락: {missing}"
    scores = [r["threat_score"] for r in threats]
    assert scores == sorted(scores, reverse=True), "Tool4: threat_score 내림차순 위반"


def block_network() -> None:
    def _blocked(*args, **kwargs):
        raise OSError("네트워크 차단 (smoke 2패스)")
    socket.socket = _blocked            # type: ignore[misc]
    socket.create_connection = _blocked  # type: ignore[assignment]


def main() -> None:
    print("1패스: 기본 실행")
    run_all("online")

    print("2패스: 네트워크 차단 + 모듈 재적재 후 재실행")
    block_network()
    for mod in [m for m in list(sys.modules) if m == "src" or m.startswith("src.")]:
        del sys.modules[mod]
    run_all("offline")

    print("PASS: 4 Tool JSON에 source·rows 존재, 네트워크 차단 재실행 통과")


if __name__ == "__main__":
    main()
