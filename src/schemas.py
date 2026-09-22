from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models import (
    ActionType,
    Archetype,
    OutcomeStatus,
    PersuasionDirection,
    QualityCheckStatus,
    TaskCategory,
)

# Prompt/çıktı metnini kabul etmemek için kasıtlı olarak yasaklanan alan adları.
# Bir istemci bu isimlerden biriyle veri göndermeye çalışırsa istek reddedilir.
FORBIDDEN_CONTENT_FIELDS = {"content", "text", "prompt", "response", "message", "raw_text", "body"}


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    department: str


class TeamCreate(BaseModel):
    name: str
    department: str


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    team_id: int
    role: str
    hire_date: date


class EmployeeCreate(BaseModel):
    full_name: str
    team_id: int
    role: str
    hire_date: date


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ToolCreate(BaseModel):
    name: str


class InteractionEventCreate(BaseModel):
    """Tek bir event'in giriş şeması.

    Gizlilik ilkesi kod seviyesinde burada uygulanır: model_config'te
    `extra="forbid"` ile şemada tanımlı olmayan hiçbir alan (dolayısıyla
    içerik/metin alanları da) kabul edilmez.
    """

    model_config = ConfigDict(extra="forbid")

    employee_id: int
    tool_id: int
    occurred_at: datetime
    session_id: str = Field(min_length=1, max_length=64)

    action_type: ActionType
    dialogue_turn_count: int = Field(default=1, ge=0)
    had_disagreement: bool = False
    persuasion_direction: PersuasionDirection = PersuasionDirection.none
    directive_language_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    politeness_marker_count: int = Field(default=0, ge=0)
    avg_sentence_length: float = Field(default=0.0, ge=0.0)
    exclamation_density: float = Field(default=0.0, ge=0.0, le=1.0)
    outcome_status: OutcomeStatus
    critical_check_flag: bool = False
    task_category: TaskCategory
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def reject_content_fields(cls, data):
        if isinstance(data, dict):
            leaked = FORBIDDEN_CONTENT_FIELDS & set(data.keys())
            if leaked:
                raise ValueError(
                    f"İçerik alanları kabul edilmez (gizlilik ilkesi ihlali): {sorted(leaked)}"
                )
        return data

    @field_validator("occurred_at")
    @classmethod
    def normalize_to_naive_utc(cls, value: datetime) -> datetime:
        """SQL Server DATETIME2 kolonları saat dilimi taşımaz; saat dilimli
        bir değer gelirse (örn. "...+03:00") önce UTC'ye çevrilip sonra
        tzinfo düşürülür, böylece DB'ye her zaman tutarlı naive-UTC yazılır.
        """
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class InteractionEventBatchCreate(BaseModel):
    events: list[InteractionEventCreate]


class InteractionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    tool_id: int
    occurred_at: datetime
    session_id: str
    action_type: ActionType
    dialogue_turn_count: int
    had_disagreement: bool
    persuasion_direction: PersuasionDirection
    directive_language_ratio: float
    politeness_marker_count: int
    avg_sentence_length: float
    exclamation_density: float
    outcome_status: OutcomeStatus
    critical_check_flag: bool
    task_category: TaskCategory
    input_tokens: int
    output_tokens: int


class InteractionEventBatchResult(BaseModel):
    accepted_count: int
    rejected_count: int
    errors: list[str] = []


class EmployeeScore(BaseModel):
    employee_id: int
    full_name: str
    team_id: int
    period_start: date
    period_end: date
    usage_score: float
    approval_score: float
    dialogue_score: float
    tone_score: float
    outcome_score: float
    critical_thinking_score: float
    composite_score: float
    archetype: Archetype
    computed_at: datetime


class TeamScore(BaseModel):
    team_id: int
    team_name: str
    employee_count: int
    avg_composite_score: float
    archetype_distribution: dict[str, int]
    period_start: date
    period_end: date


class CompanyScore(BaseModel):
    employee_count: int
    avg_composite_score: float
    avg_usage_score: float
    avg_approval_score: float
    avg_dialogue_score: float
    avg_tone_score: float
    avg_outcome_score: float
    avg_critical_thinking_score: float
    archetype_distribution: dict[str, int]
    period_start: date
    period_end: date


class ScoreTrendPoint(BaseModel):
    period_start: date
    period_end: date
    avg_composite_score: float
    employee_count: int


class ToolCostBreakdown(BaseModel):
    tool_name: str
    event_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class CostSummary(BaseModel):
    """Maliyet & verimlilik özeti. Para birimi her zaman USD'dir.

    `efficient_token_ratio`: harcanan token'ların ne kadarının kabul edilen
    (action_type == accepted) etkileşimlere ait olduğunu gösterir -- yüksek
    oran, token'ların "mantıklı" (sonuç üreten) kullanıldığını, düşük oran
    ise reddedilen/terk edilen denemelere token harcandığını gösterir.
    """

    scope: str
    scope_id: int | None
    scope_name: str | None
    event_count: int
    accepted_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    avg_cost_per_event_usd: float
    efficient_token_ratio: float
    by_tool: list[ToolCostBreakdown]
    period_start: date | None
    period_end: date | None


# ---------------------------------------------------------------------------
# Bağlayıcılar (connectors): gerçek AI araçlarından gelen ham etkileşimler.
#
# Bu şema, InteractionEventCreate'in aksine içerik TAŞIR -- bilinçli olarak.
# `POST /events` gizlilik ilkesini kod seviyesinde zorlayan "davranışsal"
# kapıdır; `POST /connectors/...` ise sinyal çıkarımının sunucuda yapıldığı,
# içeriğin saklanıp saklanmayacağına `settings.capture_content`'in karar
# verdiği "tam erişim" kapısıdır.
# ---------------------------------------------------------------------------
class ConnectorToolCall(BaseModel):
    name: str
    target: str | None = None
    is_error: bool = False
    denied: bool = False


class ConnectorExchangeIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=64)
    turn_index: int = Field(ge=0)
    started_at: datetime
    ended_at: datetime | None = None
    model: str | None = None
    prompt_text: str = ""
    response_text: str = ""
    feedback_text: str | None = None
    tool_calls: list[ConnectorToolCall] = []
    usage: dict[str, int] = {}
    interrupted: bool = False
    project: str | None = None
    git_branch: str | None = None

    @field_validator("started_at", "ended_at")
    @classmethod
    def normalize_dt(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class ConnectorExchangeBatch(BaseModel):
    source: str = Field(default="claude_code", max_length=40)
    employee_full_name: str = Field(min_length=1, max_length=200)
    team_name: str | None = None
    role: str | None = None
    tool_name: str = "Claude"
    exchanges: list[ConnectorExchangeIn]


class ConnectorExchangeResult(BaseModel):
    employee_id: int
    employee_full_name: str
    received: int
    created: int
    updated: int
    classifier: str
    capture_content: bool
    errors: list[str] = []


class LiveInteractionRead(BaseModel):
    event_id: int
    employee_id: int
    employee_full_name: str
    tool_name: str
    source: str | None
    external_id: str | None
    session_id: str
    occurred_at: datetime
    dialogue_turn_count: int
    action_type: ActionType
    had_disagreement: bool
    persuasion_direction: PersuasionDirection
    outcome_status: OutcomeStatus
    critical_check_flag: bool
    task_category: TaskCategory
    directive_language_ratio: float
    politeness_marker_count: int
    avg_sentence_length: float
    exclamation_density: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str | None = None
    project: str | None = None
    classifier: str | None = None
    prompt_text: str | None = None
    response_text: str | None = None
    feedback_text: str | None = None
    tool_calls: list[dict] | None = None
    signals: dict | None = None


class ConnectorSourceStatus(BaseModel):
    source: str
    event_count: int
    session_count: int
    employee_count: int
    first_occurred_at: datetime | None
    last_occurred_at: datetime | None


class ProjectSummary(BaseModel):
    project: str
    event_count: int
    employee_count: int
    session_count: int
    first_occurred_at: datetime | None
    last_occurred_at: datetime | None


class ConnectorStatus(BaseModel):
    capture_content: bool
    classifier_mode: str
    claude_available: bool
    sources: list[ConnectorSourceStatus]


class QualityCheckRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_at: datetime
    check_name: str
    status: QualityCheckStatus
    affected_row_count: int
    details: str | None


class QualityReport(BaseModel):
    generated_at: datetime
    checks: list[QualityCheckRunRead]
    overall_status: QualityCheckStatus
