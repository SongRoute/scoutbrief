"""
labels.py — 소표본 라벨러. CONTRACT §5, config.SMALL_SAMPLE_PA 기준.
결정론. LLM 호출 없음.
"""
import config


def small_sample_banner(pa_total: int) -> str:
    """matchup 섹션 상단 배너. PA가 기준 미만일 때만 반환."""
    if pa_total < config.SMALL_SAMPLE_PA:
        return f"⚠️ 소표본 주의: 이정후 vs 이 투수 대결 {pa_total} PA — 통계적 신뢰도 낮음."
    return ""


def vsl_low_n_label(vsL_pitches: int) -> str:
    """vsL 투구수 부족 시 라벨."""
    if vsL_pitches < config.VSL_LOW_N_PITCHES:
        return "vsL_low_n"
    return ""
