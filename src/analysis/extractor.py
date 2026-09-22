"""Ham etkileşim -> interaction_events alanları.

Deterministik alanlar (token, tur sayısı, cümle istatistikleri) her zaman
yerel hesaplanır. Yorum gerektiren alanlar önce heuristikle üretilir; Claude
sınıflandırıcı kullanılabiliyorsa onun kararı üstüne yazılır. Her iki sonuç
da (gerekçeyle birlikte) `signals` sözlüğünde saklanır -- dashboard'daki
"nasıl çıkarıldı" görünümü bunu gösterir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.analysis import claude_classifier
from src.analysis.heuristics import heuristic_signals
from src.config import settings

JUDGEMENT_FIELDS = (
    "action_type",
    "had_disagreement",
    "persuasion_direction",
    "outcome_status",
    "critical_check_flag",
    "task_category",
    "directive_language_ratio",
    "politeness_marker_count",
)


@dataclass
class ExtractionResult:
    event_fields: dict[str, Any]
    signals: dict[str, Any] = field(default_factory=dict)
    classifier: str = "heuristic"


def _classifier_mode() -> str:
    mode = (settings.signal_classifier or "auto").lower()
    if mode == "heuristic":
        return "heuristic"
    if mode == "claude":
        return "claude"
    return "claude" if claude_classifier.available() else "heuristic"


async def extract(
    *,
    prompt_text: str,
    response_text: str,
    feedback_text: str | None,
    tool_calls: list[dict],
    usage: dict[str, int],
    interrupted: bool,
    turn_index: int,
) -> ExtractionResult:
    heur = heuristic_signals(prompt_text, response_text, feedback_text, tool_calls, interrupted)
    stats = heur.pop("_stats")
    final = dict(heur)
    classifier = "heuristic"
    claude_result: dict | None = None

    if _classifier_mode() == "claude":
        claude_result = await claude_classifier.classify(prompt_text, response_text, feedback_text, tool_calls, interrupted)
        if claude_result is not None:
            classifier = "claude"
            for key in JUDGEMENT_FIELDS:
                if key in claude_result:
                    final[key] = claude_result[key]
            # Kesinti/red gibi sert kanıtlar model yorumunu ezer.
            if interrupted or any(t.get("denied") for t in tool_calls):
                final["action_type"] = "rejected"
                final["had_disagreement"] = True
                final["outcome_status"] = "abandoned"
        elif (settings.signal_classifier or "auto").lower() == "claude":
            classifier = "heuristic (claude unavailable)"

    # Faturalandırma eşdeğeri girdi token'ı: bir tur içinde her araç çağrısı
    # tüm bağlamı cache'ten yeniden okur; bunlar ham sayıda devasa görünür
    # ama ~%10 fiyatlandırılır (cache yazma ~%125). Ham değerler usage_json'da
    # olduğu gibi saklanır.
    input_tokens = round(
        int(usage.get("input_tokens", 0))
        + 1.25 * int(usage.get("cache_creation_input_tokens", 0))
        + 0.10 * int(usage.get("cache_read_input_tokens", 0))
    )
    output_tokens = int(usage.get("output_tokens", 0))

    event_fields = {
        "action_type": final["action_type"],
        "dialogue_turn_count": max(0, int(turn_index)),
        "had_disagreement": bool(final["had_disagreement"]),
        "persuasion_direction": final["persuasion_direction"],
        "directive_language_ratio": float(final["directive_language_ratio"]),
        "politeness_marker_count": int(final["politeness_marker_count"]),
        "avg_sentence_length": float(final["avg_sentence_length"]),
        "exclamation_density": float(final["exclamation_density"]),
        "outcome_status": final["outcome_status"],
        "critical_check_flag": bool(final["critical_check_flag"]),
        "task_category": final["task_category"],
        "input_tokens": max(0, input_tokens),
        "output_tokens": max(0, output_tokens),
    }
    signals = {
        "classifier": classifier,
        "final": {k: event_fields[k] for k in JUDGEMENT_FIELDS},
        "heuristic": {k: heur[k] for k in JUDGEMENT_FIELDS},
        "claude": claude_result,
        "text_stats": stats,
        "usage": usage,
        "interrupted": interrupted,
    }
    return ExtractionResult(event_fields=event_fields, signals=signals, classifier=classifier)
