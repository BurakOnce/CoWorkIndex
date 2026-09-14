"""Skorlama mantığının veritabanı gerektirmeyen birim testleri.

`_dimension_scores`, `_composite_score`, `_determine_archetype` saf
fonksiyonlardır (girdi: RawAggregates / dict, çıktı: sayısal skor ya da
Archetype) -- bu yüzden gerçek bir veritabanı bağlantısı olmadan test edilebilir.
"""

from src.models import Archetype
from src.scoring_service import (
    RawAggregates,
    _composite_score,
    _determine_archetype,
    _dimension_scores,
)


def _agg(**overrides) -> RawAggregates:
    base = RawAggregates.empty().__dict__.copy()
    base.update(overrides)
    return RawAggregates(**base)


def test_empty_aggregates_yield_zero_scores():
    scores = _dimension_scores(RawAggregates.empty())
    assert all(v == 0.0 for v in scores.values())


def test_dimension_scores_stay_within_bounds():
    agg = _agg(
        event_count=50,
        distinct_tools=4,
        distinct_task_categories=4,
        accepted_ratio=0.9,
        rejected_ratio=0.3,
        avg_dialogue_turns=8,
        disagreement_ratio=0.6,
        ai_persuaded_ratio=1.0,
        avg_directive_ratio=1.0,
        avg_politeness=10,
        avg_exclamation_density=1.0,
        production_ratio=1.0,
        abandoned_ratio=0.0,
        critical_check_ratio=1.0,
    )
    scores = _dimension_scores(agg)
    for name, value in scores.items():
        assert 0.0 <= value <= 100.0, f"{name} sınır dışında: {value}"


def test_copy_paster_profile_scores_low_on_critical_thinking():
    copy_paster = _agg(
        event_count=20,
        accepted_ratio=0.9,
        rejected_ratio=0.05,
        avg_dialogue_turns=1.0,
        disagreement_ratio=0.02,
        critical_check_ratio=0.02,
        production_ratio=0.5,
        abandoned_ratio=0.2,
    )
    dialogue_partner = _agg(
        event_count=20,
        accepted_ratio=0.55,
        rejected_ratio=0.15,
        avg_dialogue_turns=5.0,
        disagreement_ratio=0.3,
        critical_check_ratio=0.4,
        production_ratio=0.75,
        abandoned_ratio=0.05,
    )

    copy_paster_scores = _dimension_scores(copy_paster)
    dialogue_partner_scores = _dimension_scores(dialogue_partner)

    assert copy_paster_scores["critical_thinking_score"] < dialogue_partner_scores["critical_thinking_score"]
    assert copy_paster_scores["dialogue_score"] < dialogue_partner_scores["dialogue_score"]


def test_composite_score_uses_configured_weights():
    dims = {
        "usage_score": 100.0,
        "approval_score": 0.0,
        "dialogue_score": 0.0,
        "tone_score": 0.0,
        "outcome_score": 0.0,
        "critical_thinking_score": 0.0,
    }
    # weights.yaml içinde usage_score ağırlığı 0.15 -> kompozit skor 15 olmalı
    assert _composite_score(dims) == 15.0


def test_determine_archetype_passive_user():
    agg = _agg(event_count=2, avg_dialogue_turns=1.0)
    assert _determine_archetype(agg) == Archetype.passive_user


def test_determine_archetype_skeptic():
    agg = _agg(
        event_count=20,
        rejected_ratio=0.4,
        disagreement_ratio=0.3,
        critical_check_ratio=0.35,
    )
    assert _determine_archetype(agg) == Archetype.skeptic


def test_determine_archetype_commander():
    agg = _agg(event_count=20, avg_directive_ratio=0.8, avg_politeness=0.2)
    assert _determine_archetype(agg) == Archetype.commander


def test_determine_archetype_defaults_to_dialogue_partner():
    agg = _agg(event_count=20, avg_dialogue_turns=3.0, production_ratio=0.6)
    assert _determine_archetype(agg) == Archetype.dialogue_partner
