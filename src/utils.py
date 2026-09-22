from datetime import datetime, timedelta, timezone, tzinfo


def utcnow() -> datetime:
    """Naive UTC 'now'. SQL Server DATETIME2 kolonları saat dilimi taşımaz;
    tutarlılık için uygulama genelinde zaman damgaları hep bu şekilde --
    naive ama daima UTC -- üretilir.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_tz(name: str = "Europe/Istanbul") -> tzinfo:
    """Kullanıcıya dönük yerel saat dilimi (Türkiye: UTC+3, yaz saati yok).
    tzdata yoksa sabit +3'e düşer."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=3))


def local_naive_to_utc(value: datetime, tz: tzinfo | None = None) -> datetime:
    """Saat dilimi belirtilmemiş bir kullanıcı girdisini (örn. Excel'deki
    tarih) yerel saat kabul edip naive-UTC'ye çevirir. Zaten saat dilimli
    bir değer geldiyse yalnızca UTC'ye çevrilir."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz or local_tz())
    return value.astimezone(timezone.utc).replace(tzinfo=None)
