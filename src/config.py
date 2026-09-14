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

    weights_path: Path = BASE_DIR / "config" / "weights.yaml"
    archetype_rules_path: Path = BASE_DIR / "config" / "archetype_rules.yaml"
    pricing_path: Path = BASE_DIR / "config" / "pricing.yaml"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
