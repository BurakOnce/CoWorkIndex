import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Unicode,
    UniqueConstraint,
    UnicodeText,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

# Tüm zaman damgaları uygulama genelinde naive UTC olarak tutulur (SQL
# Server'ın DATETIMEOFFSET karmaşıklığından kaçınmak için). DB tarafındaki
# varsayılan değer GETUTCDATE() ile üretilir.
UTC_NOW_SERVER_DEFAULT = text("GETUTCDATE()")


def _enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    """SQLAlchemy varsayılan olarak Python Enum üyelerini `.name` ile DB'ye
    yazar. Bizim enum'larımızda `.value` insan tarafından okunabilir/Türkçe
    string'ler taşıyor (örn. Archetype.passive_user -> "pasif_kullanici");
    bu yüzden `.value` kullanılacağını açıkça belirtmek gerekiyor, aksi
    halde ad/değer farklı olduğunda (örn. Archetype) INSERT sırasında
    geçersiz değer hatası alınır. SQL Server'da native ENUM tipi yok --
    SQLAlchemy bunu VARCHAR + CHECK constraint olarak modelliyor.
    """
    return Enum(enum_cls, name=name, values_callable=lambda obj: [e.value for e in obj])


class ActionType(str, enum.Enum):
    accepted = "accepted"
    rejected = "rejected"
    edited = "edited"


class PersuasionDirection(str, enum.Enum):
    ai_persuaded_user = "ai_persuaded_user"
    user_persuaded_ai = "user_persuaded_ai"
    none = "none"


class OutcomeStatus(str, enum.Enum):
    production = "production"
    test_only = "test_only"
    abandoned = "abandoned"


class TaskCategory(str, enum.Enum):
    code = "code"
    writing = "writing"
    analysis = "analysis"
    other = "other"


class Archetype(str, enum.Enum):
    copy_paster = "kopyala_yapistirci"
    dialogue_partner = "diyalog_ortagi"
    skeptic = "supheci"
    commander = "emir_verici"
    passive_user = "pasif_kullanici"


class QualityCheckStatus(str, enum.Enum):
    passed = "passed"
    warning = "warning"
    failed = "failed"


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Unicode/UnicodeText (-> NVARCHAR/NTEXT on SQL Server): serbest metin
    # Türkçe içerebilir (ş, ğ, ı, İ gibi Latin1/CP1252'de bulunmayan
    # karakterler). Bunlar için sıradan String/Text (VARCHAR) kullanmak,
    # SQL Server'ın varsayılan koleksiyonuna bağlı olarak bu karakterlerin
    # sessizce en yakın ASCII karaktere dönüştürülüp kaybolmasına yol açar.
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False, unique=True)
    department: Mapped[str] = mapped_column(Unicode(120), nullable=False)

    employees: Mapped[list["Employee"]] = relationship(back_populates="team")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="NO ACTION"), nullable=False
    )
    role: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)

    team: Mapped["Team"] = relationship(back_populates="employees")
    events: Mapped[list["InteractionEvent"]] = relationship(back_populates="employee")
    score_snapshots: Mapped[list["ScoreSnapshot"]] = relationship(back_populates="employee")


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(80), nullable=False, unique=True)

    events: Mapped[list["InteractionEvent"]] = relationship(back_populates="tool")


class InteractionEvent(Base):
    """Tek bir AI etkileşiminin davranışsal meta-sinyalleri.

    Kasıtlı olarak: prompt/çıktı içeriğine ait hiçbir kolon yok. Bu tablo
    yalnızca "ne oldu" bilgisini tutar, "ne söylendi" bilgisini değil.
    """

    __tablename__ = "interaction_events"
    __table_args__ = (
        CheckConstraint(
            "directive_language_ratio BETWEEN 0 AND 1", name="ck_directive_language_ratio_range"
        ),
        CheckConstraint("dialogue_turn_count >= 0", name="ck_dialogue_turn_count_nonneg"),
        CheckConstraint("politeness_marker_count >= 0", name="ck_politeness_marker_count_nonneg"),
        CheckConstraint("avg_sentence_length >= 0", name="ck_avg_sentence_length_nonneg"),
        CheckConstraint(
            "exclamation_density BETWEEN 0 AND 1", name="ck_exclamation_density_range"
        ),
        CheckConstraint("input_tokens >= 0", name="ck_input_tokens_nonneg"),
        CheckConstraint("output_tokens >= 0", name="ck_output_tokens_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="NO ACTION"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    action_type: Mapped[ActionType] = mapped_column(_enum_column(ActionType, "action_type_enum"), nullable=False)
    dialogue_turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    had_disagreement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    persuasion_direction: Mapped[PersuasionDirection] = mapped_column(
        _enum_column(PersuasionDirection, "persuasion_direction_enum"),
        nullable=False,
        default=PersuasionDirection.none,
    )
    directive_language_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    politeness_marker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_sentence_length: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    exclamation_density: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_status: Mapped[OutcomeStatus] = mapped_column(
        _enum_column(OutcomeStatus, "outcome_status_enum"), nullable=False
    )
    critical_check_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    task_category: Mapped[TaskCategory] = mapped_column(
        _enum_column(TaskCategory, "task_category_enum"), nullable=False
    )
    # Token sayıları da davranışsal/kullanım meta-sinyalidir, içerik değildir
    # (tıpkı bir dosyanın boyutu gibi) -- "içerik değil, davranış" ilkesini
    # bozmaz. Maliyet hesabı için kullanılır (bkz. src/cost_service.py).
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Bağlayıcı (connector) kaynağı ve kaynaktaki kimlik: aynı etkileşim
    # tekrar gönderildiğinde upsert için (örn. "claude_code" + "session:uuid").
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Proje adı (klasörün son parçası). Bağlam meta verisidir; ?project=
    # filtresiyle skor ve maliyet proje bazında analiz edilebilir.
    project: Mapped[str | None] = mapped_column(Unicode(200), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=UTC_NOW_SERVER_DEFAULT)

    employee: Mapped["Employee"] = relationship(back_populates="events")
    tool: Mapped["Tool"] = relationship(back_populates="events")
    content: Mapped["InteractionContent | None"] = relationship(
        back_populates="event", uselist=False, cascade="all, delete-orphan"
    )


class InteractionContent(Base):
    """Opsiyonel içerik yakalama katmanı (bkz. settings.capture_content).

    Ürünün varsayılan ilkesi "içerik değil, davranış"tır ve
    `interaction_events` bu ilkeyi taşır. Bu tablo ise bilinçli olarak
    ayrıdır: bir bağlayıcı içerik yakalamayı açtığında ham prompt/cevap
    metni, araç çağrıları, token kullanımı ve çıkarılan sinyallerin
    gerekçesi buraya yazılır. Kapatıldığında tek satır bile oluşmaz ve
    ürün yine tamamen içeriksiz çalışır.
    """

    __tablename__ = "interaction_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("interaction_events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    project: Mapped[str | None] = mapped_column(Unicode(400), nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    response_text: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    tool_calls_json: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    usage_json: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    signals_json: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    classifier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=UTC_NOW_SERVER_DEFAULT)

    event: Mapped["InteractionEvent"] = relationship(back_populates="content")


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    __table_args__ = (
        UniqueConstraint("employee_id", "period_start", "period_end", name="uq_employee_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    usage_score: Mapped[float] = mapped_column(Float, nullable=False)
    approval_score: Mapped[float] = mapped_column(Float, nullable=False)
    dialogue_score: Mapped[float] = mapped_column(Float, nullable=False)
    tone_score: Mapped[float] = mapped_column(Float, nullable=False)
    outcome_score: Mapped[float] = mapped_column(Float, nullable=False)
    critical_thinking_score: Mapped[float] = mapped_column(Float, nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    archetype: Mapped[Archetype] = mapped_column(_enum_column(Archetype, "archetype_enum"), nullable=False)

    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=UTC_NOW_SERVER_DEFAULT)

    employee: Mapped["Employee"] = relationship(back_populates="score_snapshots")


class QualityCheckRun(Base):
    __tablename__ = "quality_check_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, server_default=UTC_NOW_SERVER_DEFAULT)
    check_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[QualityCheckStatus] = mapped_column(
        _enum_column(QualityCheckStatus, "quality_check_status_enum"), nullable=False
    )
    affected_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # UnicodeText: mesajlar Türkçe içerir (örn. "eşiğini aştı") -- bkz. Team
    # sınıfındaki not.
    details: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
