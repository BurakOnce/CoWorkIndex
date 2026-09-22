"""Yorum gerektiren sinyalleri Claude'a sınıflandırtır (Anthropic Messages API).

Anahtar (ANTHROPIC_API_KEY) yoksa `available()` False döner ve çağıran taraf
heuristik sonucu kullanır. Model çıktısı katı bir JSON şemasına zorlanır;
parse edilemezse None döner (yine heuristik devreye girer).
"""

from __future__ import annotations

import json
import re

import httpx

from src.config import settings

API_URL = "https://api.anthropic.com/v1/messages"
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

VALID = {
    "action_type": {"accepted", "rejected", "edited"},
    "persuasion_direction": {"ai_persuaded_user", "user_persuaded_ai", "none"},
    "outcome_status": {"production", "test_only", "abandoned"},
    "task_category": {"code", "writing", "analysis", "other"},
}

SYSTEM_PROMPT = """You are a behavioral analyst for an AI-usage analytics product.
You receive ONE exchange between a user and an AI coding assistant: the user's prompt,
the assistant's response (text + tools used), and the user's NEXT prompt (their feedback).
Classify the user's BEHAVIOR. Judge the user, not the assistant. Output ONLY a JSON object
with exactly these keys:

- action_type: "accepted" (user moved on / was satisfied), "rejected" (user refused, undid,
  interrupted or said it is wrong without redirecting), "edited" (user corrected or redirected
  the assistant with new instructions).
- had_disagreement: true if the user pushed back, objected or expressed dissatisfaction.
- persuasion_direction: "user_persuaded_ai" if the user overrode the assistant's approach,
  "ai_persuaded_user" if the assistant argued for something and the user accepted it,
  otherwise "none".
- outcome_status: "production" if the work was accepted into the project (files changed and
  kept, committed, or clearly adopted), "test_only" if it was exploratory / read-only /
  question-answer, "abandoned" if the result was discarded or rejected.
- critical_check_flag: true if the user asked to verify, test, double-check, or questioned correctness.
- task_category: "code", "writing" (docs, presentations, translations, prose), "analysis"
  (explanations, comparisons, reasoning), or "other".
- directive_language_ratio: 0.0-1.0 share of the user's sentences written as commands/imperatives.
- politeness_marker_count: integer count of politeness markers (please, thanks, polite request forms).
- rationale: one short sentence (max 25 words) explaining the classification.

Turkish and English are both possible. Be strict about JSON validity."""


def available() -> bool:
    return bool(settings.anthropic_api_key)


def _trim(text: str | None, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + " …[kırpıldı]"


def build_user_message(prompt: str, response: str, feedback: str | None, tool_calls: list[dict], interrupted: bool) -> str:
    tools = [
        f"- {t.get('name')}{' ' + str(t.get('target')) if t.get('target') else ''}"
        f"{' [DENIED]' if t.get('denied') else ''}{' [ERROR]' if t.get('is_error') else ''}"
        for t in tool_calls[:30]
    ]
    return (
        f"USER PROMPT:\n{_trim(prompt, 2500)}\n\n"
        f"ASSISTANT RESPONSE (text):\n{_trim(response, 1800)}\n\n"
        f"TOOLS USED BY ASSISTANT:\n{chr(10).join(tools) if tools else '- none'}\n\n"
        f"USER INTERRUPTED THE ASSISTANT: {'yes' if interrupted else 'no'}\n\n"
        f"USER'S NEXT PROMPT (feedback):\n{_trim(feedback, 1200) if feedback else '(no further message yet)'}"
    )


def _coerce(data: dict) -> dict | None:
    try:
        out = {
            "action_type": str(data.get("action_type", "")).strip(),
            "had_disagreement": bool(data.get("had_disagreement", False)),
            "persuasion_direction": str(data.get("persuasion_direction", "none")).strip(),
            "outcome_status": str(data.get("outcome_status", "")).strip(),
            "critical_check_flag": bool(data.get("critical_check_flag", False)),
            "task_category": str(data.get("task_category", "other")).strip(),
            "directive_language_ratio": max(0.0, min(1.0, float(data.get("directive_language_ratio", 0.0)))),
            "politeness_marker_count": max(0, int(data.get("politeness_marker_count", 0))),
            "rationale": str(data.get("rationale", ""))[:300],
        }
    except (TypeError, ValueError):
        return None
    for key, allowed in VALID.items():
        if out[key] not in allowed:
            return None
    return out


async def classify(prompt: str, response: str, feedback: str | None, tool_calls: list[dict], interrupted: bool) -> dict | None:
    if not available():
        return None
    body = {
        "model": settings.anthropic_model,
        "max_tokens": 400,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_user_message(prompt, response, feedback, tool_calls, interrupted)}],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key or "",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(API_URL, json=body, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    text = "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    result = _coerce(data)
    if result is not None:
        result["_model"] = payload.get("model", settings.anthropic_model)
        usage = payload.get("usage") or {}
        result["_classifier_tokens"] = {
            "input": int(usage.get("input_tokens", 0) or 0),
            "output": int(usage.get("output_tokens", 0) or 0),
        }
    return result
