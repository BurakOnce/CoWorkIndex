"""Sentetik demo verisi üretiminin saf (I/O içermeyen) mantığı.

Bu modül hem `event_simulator.py` (API'ye gerçek HTTP trafiği gibi event
gönderen CLI script) hem de `ingestion_service.py` (dashboard'daki "Test
Verisi Oluştur" butonunun tetiklediği, DB'ye doğrudan yazan servis)
tarafından paylaşılır -- aynı arketip/trend mantığının iki yerde ayrı ayrı
bakım gerektirmemesi için.
"""

import random
import uuid
from datetime import datetime, timezone

# Şirket şimdilik sabit boyutlu: demo veri üretimi ve Excel içe aktarma
# yalnızca bu kadar çalışana kullanım verisi (event) ekler, yeni çalışan
# oluşturmaz. Çalışan sayısını değiştirmek isterseniz burayı güncelleyin.
FIXED_EMPLOYEE_COUNT = 50

TEAMS = [
    ("Ürün Mühendisliği", "Teknoloji"),
    ("Veri & Analitik", "Teknoloji"),
    ("Müşteri Deneyimi", "Operasyon"),
    ("Pazarlama", "Büyüme"),
    ("İnsan Kaynakları", "Kurumsal"),
    ("Finans", "Kurumsal"),
]

# Takımlar gerçekçi olsun diye kasıtlı olarak eşit değil -- gerçek
# şirketlerde takım büyüklükleri genelde birbirine yakın olmaz. Toplamı
# FIXED_EMPLOYEE_COUNT'a eşit olmalı; eşit değilse `team_assignment_sequence`
# oranı koruyarak ölçekler.
TEAM_SIZE_TARGETS = {
    "Ürün Mühendisliği": 12,
    "Finans": 11,
    "Veri & Analitik": 9,
    "İnsan Kaynakları": 7,
    "Pazarlama": 6,
    "Müşteri Deneyimi": 5,
}


def team_assignment_sequence(total: int) -> list[str]:
    """`total` uzunluğunda, TEAM_SIZE_TARGETS oranlarına göre dengesiz/gerçekçi
    bir takım atama sırası üretir (örn. sıradaki 12 eleman "Ürün
    Mühendisliği", sonraki 11'i "Finans" olur, vb.)."""
    target_sum = sum(TEAM_SIZE_TARGETS.values())
    if total == target_sum:
        sizes = dict(TEAM_SIZE_TARGETS)
    else:
        ratio = total / target_sum
        sizes = {name: max(1, round(n * ratio)) for name, n in TEAM_SIZE_TARGETS.items()}
        diff = total - sum(sizes.values())
        largest = max(sizes, key=sizes.get)
        sizes[largest] += diff

    sequence: list[str] = []
    for name, count in sizes.items():
        sequence.extend([name] * count)
    return sequence

TOOLS = ["ChatGPT", "Copilot", "Claude", "Cursor", "Antigravity"]

# Şimdilik tüm demo/örnek veri üretimi tek bir araçla yapılıyor (Copilot) --
# gerçek çeşitlilik ileride, gerçek entegrasyon devreye girdiğinde eklenir.
DEFAULT_TOOL = "Copilot"

ROLES = ["Uzman", "Kıdemli Uzman", "Takım Lideri", "Müdür", "Analist"]

TASK_CATEGORIES = ["code", "writing", "analysis", "other"]

ARCHETYPE_PROFILES = {
    "kopyala_yapistirci": dict(
        events_per_month=(15, 30),
        accepted_weight=0.85,
        rejected_weight=0.05,
        edited_weight=0.10,
        dialogue_turns=(1, 1),
        disagreement_prob=0.03,
        critical_check_prob=0.05,
        directive_ratio=(0.2, 0.4),
        politeness=(0, 1),
        production_prob=0.5,
        abandoned_prob=0.2,
    ),
    "diyalog_ortagi": dict(
        events_per_month=(20, 40),
        accepted_weight=0.55,
        rejected_weight=0.15,
        edited_weight=0.30,
        dialogue_turns=(3, 7),
        disagreement_prob=0.25,
        critical_check_prob=0.35,
        directive_ratio=(0.2, 0.45),
        politeness=(1, 4),
        production_prob=0.7,
        abandoned_prob=0.08,
    ),
    "supheci": dict(
        events_per_month=(10, 25),
        accepted_weight=0.35,
        rejected_weight=0.40,
        edited_weight=0.25,
        dialogue_turns=(2, 5),
        disagreement_prob=0.45,
        critical_check_prob=0.55,
        directive_ratio=(0.15, 0.35),
        politeness=(1, 3),
        production_prob=0.55,
        abandoned_prob=0.15,
    ),
    "emir_verici": dict(
        events_per_month=(15, 35),
        accepted_weight=0.6,
        rejected_weight=0.2,
        edited_weight=0.2,
        dialogue_turns=(1, 3),
        disagreement_prob=0.15,
        critical_check_prob=0.15,
        directive_ratio=(0.65, 0.95),
        politeness=(0, 1),
        production_prob=0.5,
        abandoned_prob=0.2,
    ),
    "pasif_kullanici": dict(
        events_per_month=(1, 4),
        accepted_weight=0.5,
        rejected_weight=0.2,
        edited_weight=0.3,
        dialogue_turns=(1, 1),
        disagreement_prob=0.05,
        critical_check_prob=0.05,
        directive_ratio=(0.1, 0.3),
        politeness=(0, 2),
        production_prob=0.3,
        abandoned_prob=0.4,
    ),
}


ARCHETYPE_CYCLE = list(ARCHETYPE_PROFILES.keys())
TREND_CYCLE = ["improving", "declining", "stable"]


def archetype_for(employee_id: int) -> str:
    """Çalışanın davranış arketipini id'sinden deterministik türetir.

    Kadro sabit olduğu için üretim birden fazla kez tetiklenebilir; aynı
    çalışan her seferinde aynı arketipe göre davranmalı (rastgele değişmemeli).
    """
    return ARCHETYPE_CYCLE[employee_id % len(ARCHETYPE_CYCLE)]


def trend_for(employee_id: int) -> str:
    return TREND_CYCLE[employee_id % len(TREND_CYCLE)]


def weekly_event_count(profile: dict) -> int:
    """`events_per_month` aralığını haftalık bir sayıya ölçekler (~4.3 hafta/ay).

    Skorlar artık her hafta (30 günlük kayan pencere ile) yeniden hesaplandığı
    için event üretimi de haftalık adımlarla yapılır -- bu, Zaman Trendleri
    sekmesindeki "haftalık" görünümün "aylık"tan gerçekten farklı bir eğri
    gösterebilmesi için gereken veri yoğunluğunu sağlar.
    """
    lo, hi = profile["events_per_month"]
    lo_week = max(0, round(lo / 4.3))
    hi_week = max(lo_week, round(hi / 4.3))
    return random.randint(lo_week, hi_week)


def weighted_action_type(profile: dict) -> str:
    return random.choices(
        ["accepted", "rejected", "edited"],
        weights=[profile["accepted_weight"], profile["rejected_weight"], profile["edited_weight"]],
        k=1,
    )[0]


def weighted_outcome(profile: dict) -> str:
    remaining = max(0.0, 1 - profile["production_prob"] - profile["abandoned_prob"])
    return random.choices(
        ["production", "abandoned", "test_only"],
        weights=[profile["production_prob"], profile["abandoned_prob"], remaining],
        k=1,
    )[0]


def apply_trend(profile: dict, trend: str, progress: float) -> dict:
    """progress: 0 (dönem başı) -> 1 (bugün). Trend'e göre profili hafifçe kaydırır."""
    p = dict(profile)
    if trend == "improving":
        shift = progress * 0.25
        p["accepted_weight"] = max(0.1, p["accepted_weight"] - shift * 0.3)
        p["edited_weight"] = min(0.8, p["edited_weight"] + shift * 0.3)
        p["critical_check_prob"] = min(0.9, p["critical_check_prob"] + shift)
        p["production_prob"] = min(0.9, p["production_prob"] + shift * 0.5)
    elif trend == "declining":
        shift = progress * 0.25
        p["critical_check_prob"] = max(0.02, p["critical_check_prob"] - shift)
        p["abandoned_prob"] = min(0.7, p["abandoned_prob"] + shift * 0.5)
        p["dialogue_turns"] = (max(1, p["dialogue_turns"][0] - 0), max(1, p["dialogue_turns"][1] - 1))
    return p


def build_event_payload(employee_id: int, tool_id: int, occurred_at: datetime, profile: dict) -> dict:
    """API'ye (HTTP) gönderilebilecek JSON-uyumlu bir event payload'ı üretir."""
    dialogue_turn_count = random.randint(*profile["dialogue_turns"])
    # Token sayıları diyalog turu başına kabaca sabit bir taban etrafında
    # ölçeklenir -- daha çok turlu bir etkileşim kümülatif olarak daha çok
    # token harcar. Gerçekçi bir aralık için (girdi < çıktı, LLM'lerde tipik;
    # tek bir kod/analiz görevinde bile kolayca birkaç yüz-bin token gider).
    input_tokens = random.randint(200, 900) * dialogue_turn_count
    output_tokens = random.randint(400, 1800) * dialogue_turn_count

    return {
        "employee_id": employee_id,
        "tool_id": tool_id,
        "occurred_at": occurred_at.isoformat(),
        "session_id": str(uuid.uuid4()),
        "action_type": weighted_action_type(profile),
        "dialogue_turn_count": dialogue_turn_count,
        "had_disagreement": random.random() < profile["disagreement_prob"],
        "persuasion_direction": random.choice(
            ["ai_persuaded_user", "user_persuaded_ai", "none", "none"]
        ),
        "directive_language_ratio": round(random.uniform(*profile["directive_ratio"]), 2),
        "politeness_marker_count": random.randint(*profile["politeness"]),
        "avg_sentence_length": round(random.uniform(6, 22), 1),
        "exclamation_density": round(random.uniform(0, 0.3), 2),
        "outcome_status": weighted_outcome(profile),
        "critical_check_flag": random.random() < profile["critical_check_prob"],
        "task_category": random.choice(TASK_CATEGORIES),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def payload_to_orm_kwargs(payload: dict) -> dict:
    """HTTP payload sözlüğünü `InteractionEvent(...)` constructor'ına uygun
    Python değerlerine çevirir (occurred_at: str -> naive-UTC datetime)."""
    kwargs = dict(payload)
    occurred_at = kwargs["occurred_at"]
    if isinstance(occurred_at, str):
        occurred_at = datetime.fromisoformat(occurred_at)
    if occurred_at.tzinfo is not None:
        occurred_at = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
    kwargs["occurred_at"] = occurred_at
    return kwargs
