"""
guards.py — S7 가드레일 (A레인, CONTRACT §6).
guard_input(LLM01): 인젝션 패턴 매치 시 ValueError, 통과 시 원문 반환 (§2:43).
guard_output(LLM06): 허용 패턴 우선 검사 후 차단 문장만 마스킹 — 문장 단위.
둘 다 결정론. LLM 호출 없음 (CLAUDE.md 규칙 4의 정신).

guard_output은 멱등이다 (§6 "멱등 이중방어" — label_pass 끝 + render_deploy 내부
이중 배치의 전제). guard_output(guard_output(x)) == guard_output(x):
- 통과 문장은 원문 그대로 보존된다 (재적용해도 동일 판정).
- 마스킹 치환 토큰(MASK_TOKEN)에는 BLOCK 패턴에 걸리는 문자열이 없어
  재적용 시 다시 마스킹되지 않는다.

§6의 "연봉/계약, 사생활" 차단은 계약이 정규식을 명시하지 않아 이번 세션에서
구현하지 않았다 — 임의 패턴 도입 금지, 계약 개정 안건으로 보고됨.
"""
import re

# ⚠ 계약 미정의 — CONTRACT §6 LLM01은 차단 패턴을 명시하지 않는다.
# 아래는 세션 내 합의로 도입한 잠정 패턴. 계약 개정 안건 #6.
INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"(?i)disregard\s+(the\s+)?(system|previous)",
    r"이전\s*(지시|명령|프롬프트)\s*(을|를)?\s*무시",
    r"(?i)system\s*prompt",
    r"(?i)you\s+are\s+now",
    r"(?i)</?(system|instruction)>",
]
_INJECTION_RES = [re.compile(p) for p in INJECTION_PATTERNS]

# LLM06 (CONTRACT §6:166~168 문면 그대로) — 허용 패턴 우선, 문장 단위 마스킹.
ALLOW = r"부상자\s*명단|IL\s*(등재|복귀)|결장"
BLOCK = r"(수술|재활)\s*(부위|일정|경과)|진단"
_ALLOW_RE = re.compile(ALLOW)
_BLOCK_RE = re.compile(BLOCK)

# 마스킹 치환 토큰 — BLOCK/ALLOW 어느 패턴에도 매치되지 않고 문장 종결부호가
# 없어야 한다 (멱등성: 재적용 시 재분할·재마스킹되지 않는 근거).
MASK_TOKEN = "[의료 상세 마스킹 — LLM06]"
assert not _BLOCK_RE.search(MASK_TOKEN) and not _ALLOW_RE.search(MASK_TOKEN)

# 문장 분리 — 종결부호 뒤 공백을 캡처 그룹으로 보존해 재조립이 무손실이 되게 한다
# (통과 문장·공백·개행이 바이트 단위로 원문과 일치해야 approve-what-you-see
# 해시가 유지된다).
_SENTENCE_SEP = re.compile(r"((?<=[.!?…])\s+)")


def guard_input(request: str) -> str:
    """LLM01 입력 필터 — 인젝션 패턴 매치 시 ValueError, 통과 시 원문 반환 (§2:43)."""
    for pattern in _INJECTION_RES:
        if pattern.search(request):
            raise ValueError(
                f"LLM01: 입력 인젝션 패턴 차단 — {pattern.pattern!r} 매치")
    return request


def _guard_sentence(sentence: str) -> str:
    """허용 패턴 우선: ALLOW 매치 문장은 BLOCK 검사 없이 통과 (§6:166)."""
    if _ALLOW_RE.search(sentence):
        return sentence
    if _BLOCK_RE.search(sentence):
        return MASK_TOKEN
    return sentence


def guard_output(text: str) -> str:
    """LLM06 출력 필터 — 문장 단위 마스킹. 멱등 (모듈 docstring 참조)."""
    out_lines = []
    for line in text.split("\n"):
        parts = _SENTENCE_SEP.split(line)
        # 캡처 그룹 split: 짝수 인덱스 = 문장, 홀수 인덱스 = 구분 공백(원형 보존)
        out_lines.append("".join(
            _guard_sentence(p) if i % 2 == 0 else p for i, p in enumerate(parts)))
    return "\n".join(out_lines)
