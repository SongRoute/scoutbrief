# src/llm.py — LLM 클라이언트 + 운영 파라미터 (S4, A레인)
# 모델명·temperature는 config.py에 없는 운영 파라미터다. config.py는 CONTRACT §1과
# 문자 단위 일치가 계약이라 임의 추가 불가 — 그때까지 이 모듈이 단일 위치다.
# (config.py 편입 여부는 계약 개정 안건으로 보고됨.)
# 이번 세션은 OpenAI 단일 프로바이더. ANTHROPIC_API_KEY는 예비용 —
# fallback 경로·프로바이더 분기를 만들지 않는다.
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

LLM_MODEL = os.environ.get("SCOUTBRIEF_LLM_MODEL", "gpt-4o-mini")
LLM_TEMPERATURE = 0.2

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY가 설정되지 않았습니다. 리포 루트 .env에 "
                "OPENAI_API_KEY=<키>를 넣으세요 (.env.example 참조). "
                "조용한 fallback 없음 — 즉시 실패.")
        _client = OpenAI()
    return _client


def chat(system: str, user: str) -> str:
    """단일 system+user 턴 완성. 반환은 본문 텍스트."""
    resp = _get_client().chat.completions.create(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content.strip()
