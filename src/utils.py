from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC 'now'. SQL Server DATETIME2 kolonları saat dilimi taşımaz;
    tutarlılık için uygulama genelinde zaman damgaları hep bu şekilde --
    naive ama daima UTC -- üretilir.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
