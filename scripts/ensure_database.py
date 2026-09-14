"""Hedef veritabanı yoksa oluşturur.

SQL Server container'ı (Postgres'in POSTGRES_DB'sinin aksine) belirli bir
veritabanını otomatik yaratmaz -- sadece sunucuyu ayağa kaldırır. Bu script
`master` veritabanına bağlanıp `DATABASE_URL_SYNC` içindeki veritabanı adını
yoksa oluşturur. `alembic upgrade head`'den önce çalıştırılmalıdır.

Kullanım:
    python -m scripts.ensure_database
"""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.config import settings


def ensure_database_exists() -> None:
    target_url = make_url(settings.database_url_sync)
    db_name = target_url.database
    master_url = target_url.set(database="master")

    engine = create_engine(master_url)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(
                text(f"IF DB_ID('{db_name}') IS NULL EXEC('CREATE DATABASE [{db_name}]')")
            )
    finally:
        engine.dispose()

    print(f"Veritabanı hazır: {db_name}")


if __name__ == "__main__":
    ensure_database_exists()
