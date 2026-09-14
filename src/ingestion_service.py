"""Veri yükleme servisi: hızlı demo verisi üretimi ve Excel ile toplu içe aktarma.

İki farklı "veri nereden geliyor" senaryosunu somutlaştırır -- ikisi de
şirketin sabit boyutlu çalışan kadrosuna (bkz. `demo_data.FIXED_EMPLOYEE_COUNT`)
yalnızca kullanım verisi (event) ekler, yeni çalışan oluşturmaz:

1. `seed_demo_data`: Tek tıkla sentetik/test kullanım verisi üretir.
   `src/demo_data.py` ile aynı arketip/trend mantığını kullanır ama HTTP
   round-trip yapmadan doğrudan DB session'ı üzerinden yazar.
2. `import_from_excel` / `build_template_workbook`: Gerçek bir şirketin
   kendi AI kullanım loglarını (gateway/extension'dan dışa aktarılmış
   olabilecek) toplu olarak sisteme sokmasını temsil eder. Prompt/çıktı
   içeriği burada da yok -- şablon yalnızca davranışsal meta-sinyal
   kolonları içerir.
"""

import io
import random
import uuid
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    payload_to_orm_kwargs,
    team_assignment_sequence,
    trend_for,
    weekly_event_count,
)
from src.models import Employee, InteractionEvent, Team, Tool
from src.quality_checks import run_all_quality_checks
from src.schemas import InteractionEventCreate
from src.scoring_service import compute_and_store_employee_score
from src.utils import utcnow

fake = Faker("tr_TR")

EVENT_SHEET_COLUMNS = [
    "employee_full_name",
    "tool_name",
    "occurred_at",
    "action_type",
    "dialogue_turn_count",
    "had_disagreement",
    "persuasion_direction",
    "directive_language_ratio",
    "politeness_marker_count",
    "avg_sentence_length",
    "exclamation_density",
    "outcome_status",
    "critical_check_flag",
    "task_category",
    "input_tokens",
    "output_tokens",
]


async def _get_or_create_team(session: AsyncSession, name: str) -> Team:
    team = (await session.execute(select(Team).where(Team.name == name))).scalar_one_or_none()
    if team is None:
        team = Team(name=name, department="Belirtilmemiş")
        session.add(team)
        await session.flush()
    return team


async def _get_or_create_tool(session: AsyncSession, name: str) -> Tool:
    tool = (await session.execute(select(Tool).where(Tool.name == name))).scalar_one_or_none()
    if tool is None:
        tool = Tool(name=name)
        session.add(tool)
        await session.flush()
    return tool


async def _ensure_fixed_roster(session: AsyncSession) -> list[Employee]:
    """Takım/araç referans verisini ve tam olarak `FIXED_EMPLOYEE_COUNT`
    çalışanı garanti eder. Zaten bu kadar (ya da fazla) çalışan varsa hiç
    yeni kayıt eklemez -- kadro boyutu bilinçli olarak sabittir.
    """
    teams = [await _get_or_create_team(session, name) for name, _ in TEAMS]
    for team, (_, department) in zip(teams, TEAMS, strict=True):
        team.department = department
    for name in TOOLS:
        await _get_or_create_tool(session, name)
    await session.flush()

    existing = (
        (await session.execute(select(Employee).order_by(Employee.id))).scalars().all()
    )
    missing = FIXED_EMPLOYEE_COUNT - len(existing)
    team_by_name = {t.name: t for t in teams}
    assignment = team_assignment_sequence(FIXED_EMPLOYEE_COUNT)
    for i in range(missing):
        team_name = assignment[(len(existing) + i) % len(assignment)]
        team = team_by_name[team_name]
        hire_date = fake.date_between(start_date="-5y", end_date="-30d")
        employee = Employee(
            full_name=fake.name(), team_id=team.id, role=random.choice(ROLES), hire_date=hire_date
        )
        session.add(employee)
    if missing > 0:
        await session.flush()
        existing = (
            (await session.execute(select(Employee).order_by(Employee.id))).scalars().all()
        )

    return list(existing[:FIXED_EMPLOYEE_COUNT])


async def seed_demo_data(
    session: AsyncSession,
    months: int = 6,
    seed: int | None = None,
    tool_name: str = DEFAULT_TOOL,
) -> dict:
    """Sabit kadronun `months` aylık geçmişine sentetik kullanım verisi
    (event) ekler. Dashboard'daki demo veri butonu bunu tetikler. Kadro
    zaten tamsa yeni çalışan oluşturmaz, yalnızca event ekler.

    `tool_name`: bu koşuda üretilen tüm event'lerin hangi AI aracı/modeli
    üzerinden geldiği varsayılacak (şimdilik tek bir araç seçiliyor, gerçek
    çeşitlilik gerçek entegrasyonla gelecek).
    """
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)

    employees = await _ensure_fixed_roster(session)
    tool = await _get_or_create_tool(session, tool_name)
    await session.flush()

    now = utcnow()
    # n_weeks'i önce belirleyip başlangıcı ondan türetiyoruz ki son hafta tam
    # "şimdi"ye kadar uzansın -- aksi halde birkaç günlük bir boşluk kalır ve
    # freshness kontrolü demo verisi taze olmasına rağmen uyarı verir.
    n_weeks = max(1, round(30 * months / 7))
    start = now - timedelta(days=7 * n_weeks)
    events_added = 0

    for employee in employees:
        base_profile = ARCHETYPE_PROFILES[archetype_for(employee.id)]
        trend = trend_for(employee.id)

        for week_idx in range(n_weeks):
            week_start = start + timedelta(days=7 * week_idx)
            window_end = week_start + timedelta(days=7)
            progress = week_idx / max(1, n_weeks - 1)
            profile = apply_trend(base_profile, trend, progress)
            n_events = weekly_event_count(profile)

            for _ in range(n_events):
                occurred_at = week_start + timedelta(
                    days=random.uniform(0, 6), hours=random.uniform(0, 23)
                )
                payload = build_event_payload(employee.id, tool.id, occurred_at, profile)
                session.add(InteractionEvent(**payload_to_orm_kwargs(payload)))
                events_added += 1

            await session.flush()
            # 30 günlük kayan pencereyi her hafta sonunda yeniden hesapla:
            # aylık/haftalık trend görünümlerinin gerçekten farklı eğriler
            # gösterebilmesi için haftalık çözünürlükte snapshot gerekir.
            # commit=False: yüzlerce haftalık snapshot üretilirken her birinde
            # ayrı bir round-trip'e commit atmak yerine çalışan başına tek
            # commit yapılır (performans için).
            await compute_and_store_employee_score(
                session, employee.id, period_end=window_end.date(), commit=False
            )

        await session.commit()
    checks = await run_all_quality_checks(session)
    overall = "passed"
    for check in checks:
        if check.status.value == "failed":
            overall = "failed"
            break
        if check.status.value == "warning" and overall == "passed":
            overall = "warning"

    return {
        "employees_total": len(employees),
        "events_added": events_added,
        "quality_status": overall,
    }


async def build_template_workbook(session: AsyncSession) -> bytes:
    """Excel ile toplu içe aktarma için indirilebilir şablon üretir.

    Kadro sabit olduğundan şablonda "employees" sayfası yoktur -- yalnızca
    mevcut çalışanlara referans veren bir "events" sayfası ve o çalışanların
    listelendiği salt-okunur bir referans sayfası bulunur.
    """
    employees = (
        (await session.execute(select(Employee).order_by(Employee.full_name))).scalars().all()
    )
    teams_by_id = {t.id: t.name for t in (await session.execute(select(Team))).scalars().all()}

    roster_df = pd.DataFrame(
        [
            {"full_name": e.full_name, "team": teams_by_id.get(e.team_id, ""), "role": e.role}
            for e in employees
        ]
    )

    sample_names = [e.full_name for e in employees[:2]] or ["Örnek Çalışan 1", "Örnek Çalışan 2"]

    events_df = pd.DataFrame(
        [
            {
                "employee_full_name": sample_names[0],
                "tool_name": "Copilot",
                "occurred_at": "2026-08-15 09:30:00",
                "action_type": "accepted",
                "dialogue_turn_count": 3,
                "had_disagreement": False,
                "persuasion_direction": "none",
                "directive_language_ratio": 0.2,
                "politeness_marker_count": 2,
                "avg_sentence_length": 12.5,
                "exclamation_density": 0.0,
                "outcome_status": "production",
                "critical_check_flag": True,
                "task_category": "code",
                "input_tokens": 320,
                "output_tokens": 540,
            },
            {
                "employee_full_name": sample_names[-1],
                "tool_name": "Copilot",
                "occurred_at": "2026-08-16 14:10:00",
                "action_type": "rejected",
                "dialogue_turn_count": 1,
                "had_disagreement": True,
                "persuasion_direction": "user_persuaded_ai",
                "directive_language_ratio": 0.6,
                "politeness_marker_count": 0,
                "avg_sentence_length": 8.0,
                "exclamation_density": 0.1,
                "outcome_status": "abandoned",
                "critical_check_flag": False,
                "task_category": "analysis",
                "input_tokens": 90,
                "output_tokens": 140,
            },
        ],
        columns=EVENT_SHEET_COLUMNS,
    )

    instructions_df = pd.DataFrame(
        {
            "Alan": [
                "employee_full_name",
                "tool_name",
                "action_type",
                "persuasion_direction",
                "outcome_status",
                "task_category",
                "occurred_at",
                "directive_language_ratio / exclamation_density",
                "input_tokens / output_tokens",
                "İçerik uyarısı",
            ],
            "Geçerli değerler / format": [
                "'Çalışanlar' sayfasındaki isimlerden biri olmalı (kadro sabittir, yeni çalışan bu dosyayla eklenemez)",
                f"{', '.join(TOOLS)} (veya serbest metin -- tanınmayan bir isim girilirse otomatik oluşturulur)",
                "accepted / rejected / edited",
                "ai_persuaded_user / user_persuaded_ai / none",
                "production / test_only / abandoned",
                "code / writing / analysis / other",
                "YYYY-AA-GG SS:DD:SS",
                "0 ile 1 arasında ondalık sayı",
                "0 veya pozitif tam sayı -- girdi/çıktı token sayısı (maliyet hesabı için)",
                "Bu şablon prompt/çıktı metni İÇERMEMELİDİR -- yalnızca davranışsal "
                "meta-sinyaller ve token SAYILARI (yukarıdaki kolonlar) girilir.",
            ],
        }
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        instructions_df.to_excel(writer, sheet_name="Talimatlar", index=False)
        roster_df.to_excel(writer, sheet_name="Çalışanlar (referans)", index=False)
        events_df.to_excel(writer, sheet_name="events", index=False)
    return buffer.getvalue()


async def import_from_excel(session: AsyncSession, file_bytes: bytes) -> dict:
    """Kullanıcının yüklediği Excel dosyasındaki "events" sayfasını okuyup
    DB'ye işler. Çalışanlar yalnızca mevcut kadro içinden ada göre eşleştirilir
    -- kadro sabit olduğundan bu dosyayla yeni çalışan oluşturulmaz; eşleşme
    bulunamazsa o satır hata olarak raporlanır.
    """
    errors: list[str] = []
    events_accepted = 0
    events_rejected = 0

    try:
        sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, engine="openpyxl")
    except Exception as exc:
        return {"error": f"Dosya okunamadı: {exc}"}

    events_sheet = sheets.get("events")
    if events_sheet is None:
        return {"error": "Dosyada 'events' sayfası bulunamadı"}

    missing = set(EVENT_SHEET_COLUMNS) - set(events_sheet.columns)
    if missing:
        return {"error": f"'events' sayfasında eksik kolon(lar): {sorted(missing)}"}

    employee_cache: dict[str, Employee | None] = {}
    touched_employee_ids: set[int] = set()

    for idx, row in events_sheet.iterrows():
        row_no = idx + 2
        employee_name = str(row["employee_full_name"]).strip()

        if employee_name not in employee_cache:
            employee_cache[employee_name] = (
                await session.execute(select(Employee).where(Employee.full_name == employee_name))
            ).scalar_one_or_none()
        employee = employee_cache[employee_name]

        if employee is None:
            errors.append(
                f"events satır {row_no}: çalışan bulunamadı: '{employee_name}' "
                "(kadro sabittir; şablondaki 'Çalışanlar' sayfasından bir isim kullanın)"
            )
            events_rejected += 1
            continue

        try:
            tool = await _get_or_create_tool(session, str(row["tool_name"]).strip())
            occurred_at_value = row["occurred_at"]
            occurred_at = (
                occurred_at_value.to_pydatetime()
                if isinstance(occurred_at_value, pd.Timestamp)
                else datetime.fromisoformat(str(occurred_at_value))
            )

            validated = InteractionEventCreate(
                employee_id=employee.id,
                tool_id=tool.id,
                occurred_at=occurred_at,
                session_id=f"excel-import-{row_no}-{uuid.uuid4().hex[:8]}",
                action_type=row["action_type"],
                dialogue_turn_count=int(row["dialogue_turn_count"]),
                had_disagreement=bool(row["had_disagreement"]),
                persuasion_direction=row["persuasion_direction"],
                directive_language_ratio=float(row["directive_language_ratio"]),
                politeness_marker_count=int(row["politeness_marker_count"]),
                avg_sentence_length=float(row["avg_sentence_length"]),
                exclamation_density=float(row["exclamation_density"]),
                outcome_status=row["outcome_status"],
                critical_check_flag=bool(row["critical_check_flag"]),
                task_category=row["task_category"],
                input_tokens=int(row["input_tokens"]),
                output_tokens=int(row["output_tokens"]),
            )
            session.add(InteractionEvent(**validated.model_dump()))
            touched_employee_ids.add(employee.id)
            events_accepted += 1
        except (ValidationError, ValueError, KeyError) as exc:
            errors.append(f"events satır {row_no}: {exc}")
            events_rejected += 1

    await session.commit()
    for employee_id in touched_employee_ids:
        await compute_and_store_employee_score(session, employee_id)

    return {
        "events_accepted": events_accepted,
        "events_rejected": events_rejected,
        "errors": errors,
    }
