"""Mülakat demosu için doldurulmuş, gerçekçi bir "şirket verisi" Excel'i üretir.

Bu, `src/ingestion_service.py::build_template_workbook()`'un boş şablonundan
farklıdır: burada kurgusal bir şirketin (Anka Yazılım A.Ş.) ~25 çalışanı ve
~3 aylık gerçekçi event geçmişi doldurulmuş halde üretilir -- "elimizde
şirketin verisi var, şimdi içe aktaralım" senaryosunu canlandırmak için.

Kullanım:
    python -m scripts.generate_sample_company_excel [çıktı_yolu.xlsx]
"""

import random
import sys
from datetime import timedelta

import pandas as pd
from faker import Faker

from src.demo_data import ARCHETYPE_PROFILES, DEFAULT_TOOL, ROLES, TEAMS, apply_trend, build_event_payload
from src.utils import utcnow

fake = Faker("tr_TR")
random.seed(7)
Faker.seed(7)

COMPANY_NAME = "Anka Yazılım A.Ş."
N_EMPLOYEES = 24
MONTHS = 3


def main(output_path: str) -> None:
    archetype_cycle = list(ARCHETYPE_PROFILES.keys())
    employees = []
    for i in range(N_EMPLOYEES):
        team_name, _ = random.choice(TEAMS)
        hire_date = fake.date_between(start_date="-4y", end_date="-45d")
        employees.append(
            {
                "full_name": fake.name(),
                "team": team_name,
                "role": random.choice(ROLES),
                "hire_date": hire_date.isoformat(),
                "_archetype": archetype_cycle[i % len(archetype_cycle)],
                "_trend": random.choice(["improving", "declining", "stable"]),
            }
        )

    employees_df = pd.DataFrame(
        [{k: v for k, v in e.items() if not k.startswith("_")} for e in employees]
    )

    now = utcnow()
    start = now - timedelta(days=30 * MONTHS)
    event_rows = []
    for employee in employees:
        base_profile = ARCHETYPE_PROFILES[employee["_archetype"]]
        for month_idx in range(MONTHS):
            month_start = start + timedelta(days=30 * month_idx)
            progress = month_idx / max(1, MONTHS - 1)
            profile = apply_trend(base_profile, employee["_trend"], progress)
            n_events = random.randint(*profile["events_per_month"])
            for _ in range(n_events):
                occurred_at = month_start + timedelta(
                    days=random.uniform(0, 29), hours=random.uniform(8, 19)
                )
                payload = build_event_payload(0, 0, occurred_at, profile)
                event_rows.append(
                    {
                        "employee_full_name": employee["full_name"],
                        "tool_name": DEFAULT_TOOL,
                        "occurred_at": occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "action_type": payload["action_type"],
                        "dialogue_turn_count": payload["dialogue_turn_count"],
                        "had_disagreement": payload["had_disagreement"],
                        "persuasion_direction": payload["persuasion_direction"],
                        "directive_language_ratio": payload["directive_language_ratio"],
                        "politeness_marker_count": payload["politeness_marker_count"],
                        "avg_sentence_length": payload["avg_sentence_length"],
                        "exclamation_density": payload["exclamation_density"],
                        "outcome_status": payload["outcome_status"],
                        "critical_check_flag": payload["critical_check_flag"],
                        "task_category": payload["task_category"],
                        "input_tokens": payload["input_tokens"],
                        "output_tokens": payload["output_tokens"],
                    }
                )

    events_df = pd.DataFrame(event_rows)

    info_df = pd.DataFrame(
        {
            "Alan": ["Şirket", "Çalışan Sayısı", "Dönem", "Event Sayısı", "Not"],
            "Değer": [
                COMPANY_NAME,
                str(N_EMPLOYEES),
                f"Son {MONTHS} ay",
                str(len(events_df)),
                (
                    "Bu dosya kurgusal bir şirketin AI kullanım logunun dışa aktarımını "
                    "temsil eder -- gerçek prompt/çıktı içeriği YOKTUR, yalnızca "
                    "davranışsal meta-sinyaller vardır. Dashboard > Veri Yükleme > "
                    "'Gerçek Veri İçe Aktarma' bölümünden yüklenebilir."
                ),
            ],
        }
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        info_df.to_excel(writer, sheet_name="Bilgi", index=False)
        employees_df.to_excel(writer, sheet_name="employees", index=False)
        events_df.to_excel(writer, sheet_name="events", index=False)

    print(f"{len(employees_df)} çalışan, {len(events_df)} event -> {output_path}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "anka_yazilim_ornek_veri.xlsx"
    main(out)
