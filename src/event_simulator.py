"""Sentetik veri / event simülatörü (HTTP tabanlı, CLI).

Bu script batch dosya üretmez: takım/çalışan/araç referans verisini API
üzerinden oluşturur (sabit `FIXED_EMPLOYEE_COUNT` kadar çalışana kadar
tamamlar, asla fazlasını üretmez), ardından geçmiş için event'leri gerçek
HTTP trafiği gibi `POST /events/batch` ile API'ye gönderir. Her çalışan,
id'sinden deterministik türetilen bir arketip/trend'e göre davranır ve
zaman içinde skorları artan/azalan bir eğri izler.

Aynı üretim mantığı (arketip profilleri, trend uygulaması) `src/demo_data.py`
içinde paylaşılır; dashboard'daki "Test Verisi Oluştur" butonu ise aynı
mantığı `src/ingestion_service.py` üzerinden DB'ye doğrudan yazarak (HTTP
round-trip olmadan, çok daha hızlı) çalıştırır.

Kullanım:
    python -m src.event_simulator
"""

import asyncio
import random
from datetime import timedelta

import httpx
from faker import Faker

from src.config import settings
from src.demo_data import (
    ARCHETYPE_PROFILES,
    DEFAULT_TOOL,
    FIXED_EMPLOYEE_COUNT,
    ROLES,
    TEAMS,
    TOOLS,
    apply_trend,
    archetype_for,
    build_event_payload,
    team_assignment_sequence,
    trend_for,
    weekly_event_count,
)
from src.utils import utcnow

fake = Faker("tr_TR")
random.seed(42)
Faker.seed(42)


async def ensure_fixed_roster(client: httpx.AsyncClient) -> tuple[list[dict], list[dict]]:
    """Takım/araç referans verisini ve tam olarak `FIXED_EMPLOYEE_COUNT`
    çalışanı garanti eder. Zaten bu kadar çalışan varsa yenisini oluşturmaz
    -- kadro boyutu bilinçli olarak sabittir.
    """
    teams = (await client.get("/teams")).json()
    existing_team_names = {t["name"] for t in teams}
    for name, department in TEAMS:
        if name not in existing_team_names:
            resp = await client.post("/teams", json={"name": name, "department": department})
            resp.raise_for_status()
            teams.append(resp.json())

    tools = (await client.get("/tools")).json()
    existing_tool_names = {t["name"] for t in tools}
    for name in TOOLS:
        if name not in existing_tool_names:
            resp = await client.post("/tools", json={"name": name})
            resp.raise_for_status()
            tools.append(resp.json())

    employees = (await client.get("/employees")).json()
    missing = FIXED_EMPLOYEE_COUNT - len(employees)
    team_by_name = {t["name"]: t for t in teams}
    assignment = team_assignment_sequence(FIXED_EMPLOYEE_COUNT)
    for i in range(max(0, missing)):
        team = team_by_name[assignment[(len(employees) + i) % len(assignment)]]
        hire_date = fake.date_between(start_date="-5y", end_date="-30d")
        resp = await client.post(
            "/employees",
            json={
                "full_name": fake.name(),
                "team_id": team["id"],
                "role": random.choice(ROLES),
                "hire_date": hire_date.isoformat(),
            },
        )
        resp.raise_for_status()
        employees.append(resp.json())

    return employees[:FIXED_EMPLOYEE_COUNT], tools


async def generate_events(
    client: httpx.AsyncClient,
    employees: list[dict],
    tools: list[dict],
    months: int = 6,
    tool_name: str = DEFAULT_TOOL,
) -> None:
    """Her çalışan için hafta hafta event üretir, API'ye gönderir ve her
    hafta sonu için 30 günlük kayan pencereli bir skor snapshot'ı tetikler.
    Bu, /scores/trend endpoint'inin "aylık" ve "haftalık" görünümlerinin
    gerçekten farklı eğriler gösterebilmesi için gereken çözünürlüğü sağlar.

    `tool_name`: şimdilik tüm event'ler tek bir AI aracı/modeli üzerinden
    üretiliyor (gerçek çeşitlilik gerçek entegrasyonla gelecek).
    """
    tool = next((t for t in tools if t["name"] == tool_name), tools[0])
    now = utcnow()
    # n_weeks'i önce belirleyip başlangıcı ondan türetiyoruz ki son hafta tam
    # "şimdi"ye kadar uzansın (aksi halde freshness kontrolü uyarı verir).
    n_weeks = max(1, round(30 * months / 7))
    start = now - timedelta(days=7 * n_weeks)

    for i, employee in enumerate(employees):
        base_profile = ARCHETYPE_PROFILES[archetype_for(employee["id"])]
        trend = trend_for(employee["id"])

        for week_idx in range(n_weeks):
            week_start = start + timedelta(days=7 * week_idx)
            window_end = week_start + timedelta(days=7)
            progress = week_idx / max(1, n_weeks - 1)
            profile = apply_trend(base_profile, trend, progress)
            n_events = weekly_event_count(profile)

            batch = [
                build_event_payload(
                    employee["id"],
                    tool["id"],
                    week_start + timedelta(days=random.uniform(0, 6), hours=random.uniform(0, 23)),
                    profile,
                )
                for _ in range(n_events)
            ]
            if batch:
                await _flush_batch(client, batch, quiet=True)

            await client.post(
                f"/scores/employees/{employee['id']}/recompute",
                params={"period_end": window_end.date().isoformat()},
            )

        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(employees)} çalışan işlendi")


async def _flush_batch(client: httpx.AsyncClient, batch: list[dict], quiet: bool = False) -> None:
    resp = await client.post("/events/batch", json={"events": batch})
    resp.raise_for_status()
    if not quiet:
        result = resp.json()
        print(
            f"  batch gönderildi: {result['accepted_count']} kabul, "
            f"{result['rejected_count']} red"
        )


async def main() -> None:
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=60.0) as client:
        print("Sabit kadro tamamlanıyor (takımlar, araçlar, çalışanlar)...")
        employees, tools = await ensure_fixed_roster(client)
        print(f"  {len(employees)} çalışan, {len(tools)} araç hazır")

        print("6 aylık geçmiş event trafiği API'ye gönderiliyor...")
        await generate_events(client, employees, tools, months=6)
        print("Event üretimi tamamlandı")

        print("İlk veri kalitesi koşusu tetikleniyor...")
        resp = await client.post("/quality/run")
        resp.raise_for_status()
        report = resp.json()
        print(f"  genel durum: {report['overall_status']}")

        print("Şirket geneli skor özeti çekiliyor...")
        resp = await client.get("/scores/company")
        if resp.status_code == 200:
            print(f"  {resp.json()}")


if __name__ == "__main__":
    asyncio.run(main())
