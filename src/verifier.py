"""
Verifier — CONTRACT §5.
층1: draft 텍스트에서 숫자 추출 전 패턴 소거.
층2: 소거 후 남은 숫자를 POLICY_CONSTANTS 또는 tool_results JSON에서 대조.
LLM 호출 없음. 결정론.
"""
import json
import re
from typing import Any

import config

# ---------------------------------------------------------------------------
# 층1 소거 패턴 (CONTRACT §5 전문)
# ---------------------------------------------------------------------------

_STRIP_PATTERNS = [
    re.compile(r"\[T[1-4]\]"),                        # 각주 태그
    re.compile(r"\d{4}-\d{2}-\d{2}"),                 # YYYY-MM-DD 날짜
    re.compile(r"\d{1,2}/\d{1,2}"),                   # M/D 날짜 (CONTRACT §5 원문)
    re.compile(r"20\d{2}"),                               # 연도 (CONTRACT §5 원문)
    re.compile(r"^#+\s*\d+\.", re.MULTILINE),          # 마크다운 헤더 번호
    re.compile(r"\d(?=스트라이크|볼|회|아웃)"),        # 접미사 앞 한 자리 정수 (CONTRACT §5 원문)
]

# 숫자 추출 (정수·소수 모두)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _normalize(text: str) -> str:
    for pat in _STRIP_PATTERNS:
        text = pat.sub("", text)
    return text


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _tool_results_numbers(tool_results: dict) -> set[str]:
    """tool_results JSON에서 숫자 토큰만 정확히 추출 (부분 일치 방지)."""
    serialized = json.dumps(tool_results, ensure_ascii=False)
    return set(_NUMBER_RE.findall(serialized))


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

def verify_report(draft: dict[str, str], tool_results: dict[str, Any]) -> dict[str, dict]:
    """
    반환: {section_key: {"pass": bool, "mismatches": [str]}}
    """
    corpus_numbers = _tool_results_numbers(tool_results)
    report: dict[str, dict] = {}

    for key in config.SECTION_KEYS:
        text = draft.get(key, "")
        normalized = _normalize(text)
        numbers = _extract_numbers(normalized)

        mismatches = [
            n for n in numbers
            if n not in config.POLICY_CONSTANTS and n not in corpus_numbers
        ]

        report[key] = {
            "pass": len(mismatches) == 0,
            "mismatches": mismatches,
        }

    return report
