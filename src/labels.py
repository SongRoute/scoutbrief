"""
labels.py — 소표본 라벨러. CONTRACT §7(matchup 배너), config.SMALL_SAMPLE_PA 기준.
결정론. LLM 호출 없음.
vsL 표본 부족 판정은 CONTRACT §4 Tool 4의 vsL_low_n 필드가 유일한 진실 공급원 —
여기서 재계산하지 않는다.
"""
import config


def small_sample_banner(pa_total: int) -> str:
    """matchup 섹션 상단 배너. PA가 기준 미만일 때만 반환."""
    if pa_total < config.SMALL_SAMPLE_PA:
        return f"⚠️ 소표본 주의: 이정후 vs 이 투수 대결 {pa_total} PA — 통계적 신뢰도 낮음."
    return ""
