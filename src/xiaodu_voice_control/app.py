from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI

from .config import get_settings
from .device_registry import DeviceRegistry
from .ha_client import HomeAssistantClient
from .routes import build_router
from .token_store import TokenStore


settings = get_settings()
token_store = TokenStore(settings)
device_path = Path(settings.device_config_path)
legacy_devices = token_store.get_legacy_devices()
if not device_path.exists() and legacy_devices:
    device_path.parent.mkdir(parents=True, exist_ok=True)
    device_path.write_text(
        yaml.safe_dump({"devices": legacy_devices}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    token_store.clear_legacy_devices()
elif device_path.exists() and legacy_devices:
    token_store.clear_legacy_devices()
registry = DeviceRegistry(settings.device_config_path)
registry.load()
ha_client = HomeAssistantClient(settings)

app = FastAPI(
    title="XiaoDu Voice Control Gateway",
    version="0.2.0",
    docs_url="/docs" if settings.app_debug else None,
    redoc_url="/redoc" if settings.app_debug else None,
)

app.include_router(build_router(settings, registry, ha_client, token_store))
