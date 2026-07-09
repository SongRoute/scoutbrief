# ScoutBrief 계약 문서 — 2인 병렬 개발의 인터페이스 전부
개정은 양 레인 합의 후에만. 이 문서와 config.py가 유일한 계약이다.

## 1. config.py (전문 — 이 내용이 곧 스펙)

```python
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
```

## 2. BriefState (상태 계약)

```python
from typing import TypedDict

class BriefState(TypedDict):
    request: str                    # LLM01 필터 통과 원문
    game_ctx: dict                  # MVP: config 상수 적재 (parse_request는 규칙 기반)
    tool_results: dict              # 키 고정: pitcher_recent | arsenal | bvp | bullpen_threats
                                    #   각 값: {"data": [...], "source": str, "rows": int}
    rag_notes: list[dict]           # [{"text": str, "observed_at": "YYYY-MM"}] — S7, 없으면 []
    draft: dict                     # 키 = SECTION_KEYS, 값 = 섹션 마크다운
    verify_report: dict             # 키 = SECTION_KEYS, 값 = {"pass": bool, "mismatches": [str]}
                                    #   ★ 감사 로그 전용. escalate 이후 하류에서 읽기 금지
    retry_counts: dict              # 키 = SECTION_KEYS, 기본 0
    escalated_sections: list[str]   # ★ 하류가 읽는 유일한 실패 신호
    approved: bool                  # hitl_gate만 쓴다. 초기 False
    final_report: str
```

상태 규칙:
- R1. 하류 노드는 verify_report를 읽지 않는다. escalated_sections만 신뢰.
- R2. tool_results는 f-string 금지, JSON 블록으로만 프롬프트 전달.
- R3. 섹션 키는 SECTION_KEYS 외 추가 금지.
- R4. escalate 플레이스홀더에 숫자를 넣지 않는다:
      "⚠️ [수치 검증 실패 — 분석관 직접 작성 필요]"

## 3. cache/*.csv 스키마 5종
반올림은 전부 build_cache.py에서 수행. 자리수는 아래 표기 float(n).
build_cache 공통: game_type=='R'만 (시범경기 제외).

### ① feltner_recent5.csv — 최근 5경기 투구 단위
| 컬럼 | 타입 | 비고 |
|---|---|---|
| game_date | str YYYY-MM-DD | |
| pitch_type | str | FF/SL/CH/CU 등 |
| release_speed | float(1) | mph |
| pfx_x, pfx_z | float(2) | |
| description | str | |
| zone | int, nullable | |
| stand | str | L/R |
| balls, strikes | int | 카운트별 패턴용 |
| on_base_any | int 0/1 | 주자 유무 |

### ② feltner_arsenal_2026.csv — stand × count_group × pitch_type 1행
| 컬럼 | 타입 | 비고 |
|---|---|---|
| stand | str | L/R |
| count_group | str | ALL / 2K / AHEAD / BEHIND (투수 기준) |
| pitch_type | str | |
| n | int | |
| usage_pct | float(1) | stand×count_group 내 합 100 |
| avg_velo | float(1) | |
| avg_pfx_x, avg_pfx_z | float(2) | |
| xwoba | float(3), nullable | |
| zone_top2 | str | 예: "7,9" |

### ③ bvp_lee_feltner.csv — 구종별 1행, 통산 합계는 반복 컬럼
| 컬럼 | 타입 | 비고 |
|---|---|---|
| pitch_type | str | |
| n | int | 투구 수 |
| xwoba | float(3), nullable | |
| pa_total | int | 전 행 동일값 반복 |
| ab_total, hits_total | int | "X타수 Y안타"용, 전 행 반복 |

### ④ col_bullpen_7d.csv — 7일 풀에서 선발 제외, 투수당 1행
| 컬럼 | 타입 |
|---|---|
| pitcher | int |
| player_name | str |
| p_throws | str L/R |
| appearances_7d, pitches_7d | int |
| last_game | str YYYY-MM-DD |
| vsL_pitches_7d | int |

### ⑤ col_pitching_season.csv — 시즌 COL 투구 전체 (유일하게 비반올림 원시 데이터)
컬럼: game_date, pitcher, player_name, p_throws, batter, stand, pitch_type,
release_speed, description, events, estimated_woba_using_speedangle,
inning, at_bat_number, pitch_number, zone

build 시 불변식 (버전 드리프트 감지선 — 제거 금지):
```python
df["pitching_team"] = np.where(df.inning_topbot == "Top", df.home_team, df.away_team)
assert (df["pitching_team"] == "COL").all(), "pybaseball team= 필터 의미 변경 — 버전 드리프트"
```

## 4. MCP Tool 시그니처 4종 (상한 4, 추가 금지)
공통 반환 래퍼: {"data": [...], "source": "statcast(cache:YYYY-MM-DD)" | "statcast(live)", "rows": int}
cache 날짜는 config.CACHE_END(캐시 조회 종료일) — 파일 mtime이 아닌 상수를 써서 결정론·재현성 보장(clone/checkout 후에도 불변).
캐시 우선. live 경로는 옵션(발표일 기본은 캐시).

1) get_pitcher_recent(pitcher_id: int, n_games: int = RECENT_GAMES) → 캐시 ①
2) get_pitch_arsenal(pitcher_id: int, season: int = 2026) → 캐시 ②
3) get_batter_vs_pitcher(batter_id: int, pitcher_id: int) → 캐시 ③ (선발 전용;
   불펜 개인 전적은 Tool 4가 흡수)
4) get_bullpen_threats(team: str, batter_id: int, days_usage: int = BULLPEN_DAYS)
   → 캐시 ④+⑤. 7일 풀 전원 반환(컷오프 없음), threat_score 내림차순.
   행 스키마:
   | 필드 | 원천 |
   |---|---|
   | pitcher_id, name, throws | ④ |
   | appearances_7d, pitches_7d, last_game, rest_days | ④ (rest_days = GAME_DATE_US − last_game) |
   | vsL_xwoba float(3) | ⑤ stand=='L' 시즌 집계 |
   | vsL_top2_usage str 예: "SL,FF" | ⑤ vsL 사용률 상위 2개 구종명 쉼표 연결 (캐시 ② zone_top2 관례). 동률: 투구수 내림차순 → 구종명 오름차순 |
   | vsL_low_n 0/1 | ⑤ vsL 투구수 < VSL_LOW_N_PITCHES |
   | bvp_pa, bvp_xwoba float(3) | ⑤ batter==LEE_JH_ID |
   | availability 0~2 | config.availability() |
   | threat_score | 아래 공식 |
   | lefty_flag 0/1 | throws=='L' |

   threat_score (결정론, Tool 내부 계산 — LLM 금지):
   suppression_weight = N+1 − rank(vsL_xwoba 오름차순)   # 낮을수록 위협 = 큰 가중치
   threat_score = availability × suppression_weight
   동률: vsL 투구수 많은 쪽 우선.
   vsL_xwoba 결측: VSL_XWOBA_IMPUTE 대입 + vsL_low_n=1 (대입값 리포트 인용 금지).
   ★ 리포트 각주는 "threat_score = 가용성×좌타억제력 (규칙 공식, config.py 정의),
     감독 성향 미반영"까지만 — 수치 임계값을 각주에 인용하지 않는다 (Verifier 방어선 보호).

## 5. Verifier 스펙 (B레인)
입력 (draft: dict, tool_results: dict) → verify_report.
층1 — 추출 전 정규화(소거): \[T[1-4]\] 각주 / 날짜(\d{4}-\d{2}-\d{2}, \d{1,2}/\d{1,2}) /
연도(20\d{2}) / 마크다운 헤더 번호(^#+\s*\d+\.) /
(스트라이크|볼|회|아웃) 접미 한 자리 정수.
층2 — POLICY_CONSTANTS 허용.
그 외 숫자는 tool_results 원본(JSON 직렬화 문자열) 내 존재해야 통과.

## 6. 가드레일 스펙 (A레인)
LLM01: 입력 인젝션 패턴 차단(ValueError). tool_results는 R2로 간접 인젝션 방어.
LLM06: 허용 패턴 우선 검사 — `부상자\s*명단|IL\s*(등재|복귀)|결장` 매치 문장은 통과.
       차단(축소) — `(수술|재활)\s*(부위|일정|경과)|진단`, 연봉/계약, 사생활.
       문장 단위 마스킹.
guard_output 위치: label_pass 끝(분석관이 마스킹된 최종본을 승인) +
deploy_report 내부(멱등 이중방어, 제거 금지).
LLM08: HMAC 승인 토큰. issue_approval_token은 그래프 외부(콘솔)에서만 호출 가능.
미승인 deploy는 PermissionError.

## 7. 리포트 섹션 구조 (SECTION_KEYS 순)
- feltner: 최근 폼(캐시①) + 구종/카운트별 패턴(캐시②, vsL 기본) + 정성노트("과거 관찰(작성시점)" 라벨)
- matchup: 섹션 상단 소표본 배너(pa_total < SMALL_SAMPLE_PA 시) + 구종별 전적(캐시③)
  + 좌타 전체 경향(캐시②)을 보조 지표로 명시
- bullpen: threat_score 순위표(전원) — 컬럼: 순위/투수(투)/만날 확률 근거/vsL 주무기/vsL xwOBA/개인 전적(PA 병기).
  표 상단 소표본 안내 1회. 좌완은 lefty_flag 표기. 이후 상위 위협 투수별 대응 전략(⚑ 추정 라벨).
- gameplan: 이정후 맞춤 공략 포인트. 모든 추정에 ⚑, 전달 금지 문구 포함.
헤더 공통: 출처 각주 [T1]~[T4] + source 메타(live 또는 cache 날짜 YYYY-MM-DD) + "분석관 승인 대기" 상태.