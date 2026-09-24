"""Maliyet & verimlilik hesaplama servisi.

Token sayıları `interaction_events`'te davranışsal bir meta-sinyal olarak
tutulur -- içerik değil, bir dosyanın boyutu gibi salt sayısal bir ölçüm;
bu yüzden "içerik değil, davranış" ilkesini bozmaz.

Fiyatlandırma DB'de değil `config/pricing.yaml`'da tutulur: fiyatlar sık
değişebilir, bunun için her seferinde migration gerekmemesi daha doğru bir
mimari tercih (tıpkı skor ağırlıklarının `weights.yaml`'da tutulması gibi).
Bu, mevcut 6 boyutlu olgunluk skorunun ağırlıklarını değiştirmez -- maliyet/
verimlilik tamamlayıcı, ayrı bir analiz katmanı olarak sunulur.

Para birimi her zaman USD'dir.
"""

from datetime import date, timedelta

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import Employee, InteractionEvent, Team, Tool
from src.schemas import CostSummary, ToolCostBreakdown


def _load_pricing() -> dict:
    with open(settings.pricing_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rates_for(pricing: dict, tool_name: str, model: str | None = None) -> dict:
    """Model biliniyorsa (bağlayıcı verisi) modele göre, yoksa araca göre fiyat.
    `models` bölümündeki anahtarlar model adı içinde geçen bir alt dize olarak
    eşleşir (örn. "claude-opus" -> "claude-opus-5", "gpt-4.1" -> "copilot/gpt-4.1"
    -- bazı bağlayıcılar vendor/model biçiminde bir tanımlayıcı gönderir)."""
    if model:
        model_l = model.lower()
        for prefix, rates in (pricing.get("models") or {}).items():
            if str(prefix).lower() in model_l:
                return rates
    return pricing.get(tool_name, pricing["_default"])


def _event_cost_usd(
    pricing: dict, tool_name: str, input_tokens: int, output_tokens: int, model: str | None = None
) -> float:
    rates = _rates_for(pricing, tool_name, model)
    return (
        input_tokens / 1_000_000 * rates["input_per_million"]
        + output_tokens / 1_000_000 * rates["output_per_million"]
    )


async def compute_cost_summary(
    session: AsyncSession,
    *,
    scope: str = "company",
    scope_id: int | None = None,
    period_end: date | None = None,
    window_days: int | None = None,
    project: str | None = None,
) -> CostSummary:
    """scope: "company" | "team" | "employee". `window_days` verilmezse
    (varsayılan) tüm geçmiş dikkate alınır -- toplam harcanan bütçe sorusu
    için bu daha doğru varsayılandır; bir pencereye kısıtlamak isterseniz
    `window_days` verin. `project` verilirse yalnızca o projenin event'leri.
    """
    pricing = _load_pricing()

    query = select(InteractionEvent, Tool.name).join(Tool, Tool.id == InteractionEvent.tool_id)
    if project:
        query = query.where(InteractionEvent.project == project)

    scope_name = None
    if scope == "employee":
        query = query.where(InteractionEvent.employee_id == scope_id)
        employee = await session.get(Employee, scope_id)
        scope_name = employee.full_name if employee else None
    elif scope == "team":
        query = query.join(Employee, Employee.id == InteractionEvent.employee_id).where(
            Employee.team_id == scope_id
        )
        team = await session.get(Team, scope_id)
        scope_name = team.name if team else None

    period_start: date | None = None
    if window_days is not None:
        period_end = period_end or date.today()
        period_start = period_end - timedelta(days=window_days)
        query = query.where(
            InteractionEvent.occurred_at >= period_start,
            InteractionEvent.occurred_at < period_end,
        )

    rows = (await session.execute(query)).all()

    event_count = len(rows)
    accepted_count = 0
    total_input = 0
    total_output = 0
    total_cost = 0.0
    accepted_tokens = 0
    by_tool: dict[str, dict] = {}

    for event, tool_name in rows:
        tokens = event.input_tokens + event.output_tokens
        cost = _event_cost_usd(pricing, tool_name, event.input_tokens, event.output_tokens, event.model)

        total_input += event.input_tokens
        total_output += event.output_tokens
        total_cost += cost

        if event.action_type.value == "accepted":
            accepted_count += 1
            accepted_tokens += tokens

        bucket = by_tool.setdefault(
            tool_name, {"event_count": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        bucket["event_count"] += 1
        bucket["input_tokens"] += event.input_tokens
        bucket["output_tokens"] += event.output_tokens
        bucket["cost_usd"] += cost

    total_tokens = total_input + total_output

    return CostSummary(
        scope=scope,
        scope_id=scope_id,
        scope_name=scope_name,
        event_count=event_count,
        accepted_count=accepted_count,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_tokens,
        total_cost_usd=round(total_cost, 4),
        avg_cost_per_event_usd=round(total_cost / event_count, 4) if event_count else 0.0,
        efficient_token_ratio=round(accepted_tokens / total_tokens, 4) if total_tokens else 0.0,
        by_tool=[
            ToolCostBreakdown(
                tool_name=name,
                event_count=b["event_count"],
                input_tokens=b["input_tokens"],
                output_tokens=b["output_tokens"],
                cost_usd=round(b["cost_usd"], 4),
            )
            for name, b in sorted(by_tool.items(), key=lambda kv: -kv[1]["cost_usd"])
        ],
        period_start=period_start,
        period_end=period_end if window_days is not None else None,
    )


async def compute_cost_summary_by_employee(
    session: AsyncSession, *, window_days: int | None = None, project: str | None = None
) -> list[CostSummary]:
    """Tüm çalışanlar için maliyet özetini tek sorguda hesaplar (dashboard'un
    tam tabloyu gösterirken çalışan başına ayrı bir istek yapmasını önler).
    """
    pricing = _load_pricing()

    query = (
        select(InteractionEvent, Tool.name, Employee.id, Employee.full_name)
        .join(Tool, Tool.id == InteractionEvent.tool_id)
        .join(Employee, Employee.id == InteractionEvent.employee_id)
    )
    if project:
        query = query.where(InteractionEvent.project == project)

    period_start: date | None = None
    period_end: date | None = None
    if window_days is not None:
        period_end = date.today()
        period_start = period_end - timedelta(days=window_days)
        query = query.where(
            InteractionEvent.occurred_at >= period_start,
            InteractionEvent.occurred_at < period_end,
        )

    rows = (await session.execute(query)).all()

    per_employee: dict[int, dict] = {}

    for event, tool_name, employee_id, full_name in rows:
        tokens = event.input_tokens + event.output_tokens
        cost = _event_cost_usd(pricing, tool_name, event.input_tokens, event.output_tokens, event.model)

        bucket = per_employee.setdefault(
            employee_id,
            {
                "full_name": full_name,
                "event_count": 0,
                "accepted_count": 0,
                "total_input": 0,
                "total_output": 0,
                "total_cost": 0.0,
                "accepted_tokens": 0,
                "by_tool": {},
            },
        )
        bucket["event_count"] += 1
        bucket["total_input"] += event.input_tokens
        bucket["total_output"] += event.output_tokens
        bucket["total_cost"] += cost
        if event.action_type.value == "accepted":
            bucket["accepted_count"] += 1
            bucket["accepted_tokens"] += tokens

        tool_bucket = bucket["by_tool"].setdefault(
            tool_name, {"event_count": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        tool_bucket["event_count"] += 1
        tool_bucket["input_tokens"] += event.input_tokens
        tool_bucket["output_tokens"] += event.output_tokens
        tool_bucket["cost_usd"] += cost

    results = []
    for employee_id, b in per_employee.items():
        total_tokens = b["total_input"] + b["total_output"]
        results.append(
            CostSummary(
                scope="employee",
                scope_id=employee_id,
                scope_name=b["full_name"],
                event_count=b["event_count"],
                accepted_count=b["accepted_count"],
                total_input_tokens=b["total_input"],
                total_output_tokens=b["total_output"],
                total_tokens=total_tokens,
                total_cost_usd=round(b["total_cost"], 4),
                avg_cost_per_event_usd=(
                    round(b["total_cost"] / b["event_count"], 4) if b["event_count"] else 0.0
                ),
                efficient_token_ratio=(
                    round(b["accepted_tokens"] / total_tokens, 4) if total_tokens else 0.0
                ),
                by_tool=[
                    ToolCostBreakdown(
                        tool_name=name,
                        event_count=t["event_count"],
                        input_tokens=t["input_tokens"],
                        output_tokens=t["output_tokens"],
                        cost_usd=round(t["cost_usd"], 4),
                    )
                    for name, t in b["by_tool"].items()
                ],
                period_start=period_start,
                period_end=period_end,
            )
        )

    results.sort(key=lambda r: -r.total_cost_usd)
    return results
