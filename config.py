# config.py — 양 레인 공통. 여기 없는 매직넘버를 코드에 쓰지 않는다.
LEE_JH_ID      = 808982          # 검증: 2026-06-25~07-08 statcast 156행
FELTNER_ID     = 663372          # 검증: 2026 COL 912행, 12/12경기 1회 등판(선발)
TEAM_OPP       = "COL"
TEAM_US        = "SF"
GAME_DATE_US   = "2026-07-09"    # KST 7/10 10:45 경기. rest_days 계산 기준일
SEASON_START   = "2026-03-25"    # 정규시즌 개막 (build_cache는 game_type=='R' 필터 병용)
CACHE_END      = "2026-07-08"    # 캐시 조회 종료일 (경기 전날까지)

SECTION_KEYS   = ["feltner", "matchup", "bullpen", "gameplan"]
SMALL_SAMPLE_PA    = 20          # 소표본 라벨 기준 (PA)
RECENT_GAMES       = 5
BULLPEN_DAYS       = 7
MAX_RETRY          = 2
VSL_LOW_N_PITCHES  = 30          # 시즌 vsL 표본 부족 플래그 기준
VSL_XWOBA_IMPUTE   = 0.320       # vsL xwOBA 결측 시 순위 계산 대입값. 리포트 인용 절대 금지
FATIGUE_PITCHES_7D     = 50      # availability 감점 기준
FATIGUE_APPEARANCES_7D = 3

# Verifier 층2 화이트리스트 — 정책 상수의 문자열 표현
POLICY_CONSTANTS = {"20", "7", "5", "2", "30"}

def availability(rest_days: int, pitches_7d: int, appearances_7d: int) -> int:
    """가용성 0~2. 결정론적 — 테스트 대상."""
    a = 2 if rest_days >= 2 else (1 if rest_days == 1 else 0)
    if pitches_7d >= FATIGUE_PITCHES_7D or appearances_7d >= FATIGUE_APPEARANCES_7D:
        a = max(a - 1, 0)
    return a
