"""CoWork Index skor hesaplama mantığı.

Skorlar bir batch job ile değil, bu servis çağrıldığında (event sonrası
senkron ya da scheduler tarafından periyodik olarak) hesaplanır. Girdi
her zaman `interaction_events` tablosundaki davranışsal meta-sinyallerdir;
prompt/çıktı içeriği hiçbir aşamada kullanılmaz.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import Archetype, InteractionEvent, ScoreSnapshot
from src.utils import utcnow

DEFAULT_WINDOW_DAYS = 30


def _load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


@dataclass
class RawAggregates:
    event_count: int
    distinct_tools: int
    distinct_task_categories: int
    accepted_ratio: float
    rejected_ratio: float
    edited_ratio: float
    avg_dialogue_turns: float
    disagreement_ratio: float
    ai_persuaded_ratio: float
    user_persuaded_ratio: float
    avg_directive_ratio: float
    avg_politeness: float
    avg_sentence_length: float
    avg_exclamation_density: float
    production_ratio: float
    abandoned_ratio: float
    test_only_ratio: float
    critical_check_ratio: float

    @staticmethod
    def empty() -> "RawAggregates":
        return RawAggregates(
            event_count=0,
            distinct_tools=0,
            distinct_task_categories=0,
            accepted_ratio=0.0,
            rejected_ratio=0.0,
            edited_ratio=0.0,
            avg_dialogue_turns=0.0,
            disagreement_ratio=0.0,
            ai_persuaded_ratio=0.0,
            user_persuaded_ratio=0.0,
            avg_directive_ratio=0.0,
            avg_politeness=0.0,
            avg_sentence_length=0.0,
            avg_exclamation_density=0.0,
            production_ratio=0.0,
            abandoned_ratio=0.0,
            test_only_ratio=0.0,
            critical_check_ratio=0.0,
        )


async def _fetch_raw_aggregates(
    session: AsyncSession,
    employee_id: int,
    period_start: date,
    period_end: date,
    project: str | None = None,
) -> RawAggregates:
    query = select(InteractionEvent).where(
        InteractionEvent.employee_id == employee_id,
        InteractionEvent.occurred_at >= period_start,
        InteractionEvent.occurred_at < period_end,
    )
    if project:
        query = query.where(InteractionEvent.project == project)
    rows = (await session.execute(query)).scalars().all()

    n = len(rows)
    if n == 0:
        return RawAggregates.empty()

    accepted = sum(1 for r in rows if r.action_type.value == "accepted")
    rejected = sum(1 for r in rows if r.action_type.value == "rejected")
    edited = sum(1 for r in rows if r.action_type.value == "edited")
    disagreement = sum(1 for r in rows if r.had_disagreement)
    ai_persuaded = sum(1 for r in rows if r.persuasion_direction.value == "ai_persuaded_user")
    user_persuaded = sum(1 for r in rows if r.persuasion_direction.value == "user_persuaded_ai")
    production = sum(1 for r in rows if r.outcome_status.value == "production")
    abandoned = sum(1 for r in rows if r.outcome_status.value == "abandoned")
    test_only = sum(1 for r in rows if r.outcome_status.value == "test_only")
    critical_check = sum(1 for r in rows if r.critical_check_flag)

    return RawAggregates(
        event_count=n,
        distinct_tools=len({r.tool_id for r in rows}),
        distinct_task_categories=len({r.task_category.value for r in rows}),
        accepted_ratio=accepted / n,
        rejected_ratio=rejected / n,
        edited_ratio=edited / n,
        avg_dialogue_turns=sum(r.dialogue_turn_count for r in rows) / n,
        disagreement_ratio=disagreement / n,
        ai_persuaded_ratio=ai_persuaded / n,
        user_persuaded_ratio=user_persuaded / n,
        avg_directive_ratio=sum(r.directive_language_ratio for r in rows) / n,
        avg_politeness=sum(r.politeness_marker_count for r in rows) / n,
        avg_sentence_length=sum(r.avg_sentence_length for r in rows) / n,
        avg_exclamation_density=sum(r.exclamation_density for r in rows) / n,
        production_ratio=production / n,
        abandoned_ratio=abandoned / n,
        test_only_ratio=test_only / n,
        critical_check_ratio=critical_check / n,
    )


def _dimension_scores(agg: RawAggregates) -> dict[str, float]:
    if agg.event_count == 0:
        return {
            "usage_score": 0.0,
            "approval_score": 0.0,
            "dialogue_score": 0.0,
            "tone_score": 0.0,
            "outcome_score": 0.0,
            "critical_thinking_score": 0.0,
        }

    # 1. Kullanım Yoğunluğu & Çeşitliliği: event hacmi + araç/görev çeşitliliği
    intensity = _clamp(agg.event_count / 40 * 60, high=60)  # 40 event/ay -> tavan civarı
    diversity = _clamp(agg.distinct_tools * 10 + agg.distinct_task_categories * 10, high=40)
    usage_score = _clamp(intensity + diversity)

    # 2. Onay/Red Dinamiği: dengeli bir onay oranı + düzeltme (edited) sağlıklıdır,
    #    salt kabul (kritiksiz kopyala-yapıştır) veya salt red aşırı uçlardır.
    approval_score = _clamp(
        100 - abs(agg.accepted_ratio - 0.6) * 80 - abs(agg.rejected_ratio - 0.15) * 40
    )

    # 3. Diyalog/Müzakere Davranışı: çok turlu diyalog + karşılıklı ikna dengesi
    dialogue_depth = _clamp(agg.avg_dialogue_turns / 4 * 70, high=70)
    negotiation_balance = _clamp(30 - abs(agg.ai_persuaded_ratio - agg.user_persuaded_ratio) * 60, low=0, high=30)
    dialogue_score = _clamp(dialogue_depth + negotiation_balance)

    # 4. İletişim Üslubu: nezaket işaretleri olumlu, aşırı emir/ünlem olumsuz
    politeness_component = _clamp(agg.avg_politeness / 3 * 50, high=50)
    directive_penalty = agg.avg_directive_ratio * 30
    exclamation_penalty = agg.avg_exclamation_density * 20
    tone_score = _clamp(100 - directive_penalty - exclamation_penalty) * 0.5 + politeness_component

    # 5. Sonuç Takibi: üretime giden iş oranı yüksek, terk edilen düşük olmalı
    outcome_score = _clamp(agg.production_ratio * 80 + (1 - agg.abandoned_ratio) * 20)

    # 6. Eleştirel Kullanım Endeksi: kritik kontrol + sağlıklı itiraz oranı
    critical_thinking_score = _clamp(
        agg.critical_check_ratio * 70 + min(agg.disagreement_ratio, 0.4) / 0.4 * 30
    )

    return {
        "usage_score": round(usage_score, 2),
        "approval_score": round(approval_score, 2),
        "dialogue_score": round(dialogue_score, 2),
        "tone_score": round(_clamp(tone_score), 2),
        "outcome_score": round(outcome_score, 2),
        "critical_thinking_score": round(critical_thinking_score, 2),
    }


def _composite_score(dimension_scores: dict[str, float]) -> float:
    weights = _load_yaml(settings.weights_path)
    total = sum(dimension_scores[dim] * weight for dim, weight in weights.items())
    return round(total, 2)


def _match_condition(agg: RawAggregates, conditions: dict) -> bool:
    for key, threshold in conditions.items():
        if key.endswith("_min"):
            field = key[: -len("_min")]
            if getattr(agg, field, 0) < threshold:
                return False
        elif key.endswith("_max"):
            field = key[: -len("_max")]
            if getattr(agg, field, 0) > threshold:
                return False
    return True


def _determine_archetype(agg: RawAggregates) -> Archetype:
    rules = _load_yaml(settings.archetype_rules_path)
    ordered = sorted(rules["archetypes"], key=lambda r: r["priority"])
    for rule in ordered:
        if _match_condition(agg, rule["conditions"]):
            return Archetype(rule["name"])
    return Archetype(rules["default"])


async def compute_and_store_employee_score(
    session: AsyncSession,
    employee_id: int,
    period_end: date | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    *,
    commit: bool = True,
) -> ScoreSnapshot:
    period_end = period_end or utcnow().date()
    period_start = period_end - timedelta(days=window_days)

    agg = await _fetch_raw_aggregates(session, employee_id, period_start, period_end)
    dims = _dimension_scores(agg)
    composite = _composite_score(dims)
    archetype = _determine_archetype(agg)

    existing = (
        await session.execute(
            select(ScoreSnapshot).where(
                ScoreSnapshot.employee_id == employee_id,
                ScoreSnapshot.period_start == period_start,
                ScoreSnapshot.period_end == period_end,
            )
        )
    ).scalar_one_or_none()

    values = {
        "computed_at": utcnow(),
        "composite_score": composite,
        "archetype": archetype,
        **dims,
    }

    if existing is not None:
        for key, value in values.items():
            setattr(existing, key, value)
        snapshot = existing
    else:
        snapshot = ScoreSnapshot(
            employee_id=employee_id,
            period_start=period_start,
            period_end=period_end,
            **values,
        )
        session.add(snapshot)

    if commit:
        await session.commit()
    else:
        # Toplu üretim (bkz. ingestion_service.seed_demo_data) her hafta
        # ayrı bir round-trip'e commit atmak yerine bunu flush ile bekletip
        # çağıran tarafta daha büyük gruplar halinde commit'ler -- yüzlerce
        # haftalık snapshot üretilirken belirgin bir performans farkı yaratır.
        await session.flush()
    await session.refresh(snapshot)
    return snapshot


async def compute_employee_score_adhoc(
    session: AsyncSession,
    employee_id: int,
    *,
    project: str | None = None,
    period_end: date | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict | None:
    """Skoru saklamadan, isteğe bağlı proje filtresiyle anlık hesaplar.

    Snapshot'lar çalışanın tüm etkileşimleri üzerinden tutulur; "yalnızca şu
    projedeki davranış" sorusu için aynı skorlama mantığı filtrelenmiş
    event'lere uygulanır. Pencerede hiç event yoksa None döner.
    """
    period_end = period_end or utcnow().date()
    period_start = period_end - timedelta(days=window_days)
    agg = await _fetch_raw_aggregates(session, employee_id, period_start, period_end, project=project)
    if agg.event_count == 0:
        return None
    dims = _dimension_scores(agg)
    return {
        "period_start": period_start,
        "period_end": period_end,
        "composite_score": _composite_score(dims),
        "archetype": _determine_archetype(agg),
        "computed_at": utcnow(),
        "event_count": agg.event_count,
        **dims,
    }


async def recompute_scores_for_employees(
    session: AsyncSession, employee_ids: list[int], window_days: int = DEFAULT_WINDOW_DAYS
) -> int:
    count = 0
    for employee_id in employee_ids:
        await compute_and_store_employee_score(session, employee_id, window_days=window_days)
        count += 1
    return count
