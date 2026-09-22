from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    database_url: str = (
        "mssql+aioodbc://sa:CoWork!2024Strong@localhost:1433/ai_usage_maturity"
        "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&MARS_Connection=yes"
    )
    database_url_sync: str = (
        "mssql+pyodbc://sa:CoWork!2024Strong@localhost:1433/ai_usage_maturity"
        "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&MARS_Connection=yes"
    )
    api_base_url: str = "http://localhost:8000"
    scheduler_enabled: bool = True
    score_recompute_interval_minutes: int = 5
    quality_audit_interval_minutes: int = 15

    # Veritabanı/API her zaman UTC; bu, kullanıcı girdilerini (Excel) yorumlamak
    # ve dashboard'da göstermek için kullanılan yerel saat dilimi (Türkiye).
    local_timezone: str = "Europe/Istanbul"

    weights_path: Path = BASE_DIR / "config" / "weights.yaml"
    archetype_rules_path: Path = BASE_DIR / "config" / "archetype_rules.yaml"
    pricing_path: Path = BASE_DIR / "config" / "pricing.yaml"

    # --- Bağlayıcılar (Claude Code vb.) ---
    # capture_content=True: bağlayıcıdan gelen ham prompt/cevap metni
    # interaction_contents tablosuna yazılır (tam erişim modu).
    # False: yalnızca davranışsal sinyaller tutulur, içerik anında atılır.
    capture_content: bool = True
    # Sinyal çıkarımı: "auto" -> API anahtarı varsa Claude, yoksa heuristik;
    # "claude" -> Claude zorunlu; "heuristic" -> hiç model çağırma.
    signal_classifier: str = "auto"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    # Bağlayıcı, çalışanı adıyla bulamazsa bu takım/rolle oluşturur.
    connector_default_team: str = "Veri & Analitik"
    connector_default_role: str = "Uzman Yardımcısı"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
