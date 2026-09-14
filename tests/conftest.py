"""Test oturumu sonunda SQLAlchemy engine'ini düzgünce kapatır.

Windows'ta async DB sürücüleri (aioodbc dahil) + ProactorEventLoop
kombinasyonu, event loop kapanırken havuzdaki bağlantılar hâlâ açıksa bir
teardown hatası (AttributeError / RuntimeError: Event loop is closed)
üretebiliyor. Bu, uygulama mantığında bir hata değil, salt test sürecinin
bitişiyle ilgili bir temizlik yarışı; engine'i loop kapanmadan önce açıkça
`dispose()` ederek önüne geçiyoruz.
"""

import pytest_asyncio

from src.db import engine


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_engine_after_tests():
    yield
    await engine.dispose()
