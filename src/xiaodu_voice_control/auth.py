from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Settings
from .ha_client import HomeAssistantClient


@dataclass(slots=True)
class BoundUser:
    username: str
    subject: str


def _redirect_uri_allowed(settings: Settings, redirect_uri: str) -> bool:
    for allowed in settings.allowed_redirect_uris:
        normalized = allowed.strip()
        if not normalized:
            continue
        if normalized.endswith("*"):
            if redirect_uri.startswith(normalized[:-1]):
                return True
            continue
        if normalized.endswith("/"):
            if redirect_uri.startswith(normalized):
                return True
            continue
        if redirect_uri == normalized:
            return True
    return False


def validate_client(
    settings: Settings,
    client_id: str,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> None:
    if client_id != settings.xiaodu_client_id:
        raise ValueError("invalid client_id")
    if client_secret is not None and client_secret != settings.xiaodu_client_secret:
        raise ValueError("invalid client_secret")
    if redirect_uri and not _redirect_uri_allowed(settings, redirect_uri):
        raise ValueError("invalid redirect_uri")


async def validate_bind_user(
    settings: Settings,
    ha_client: HomeAssistantClient,
    username: str,
    password: str,
) -> BoundUser:
    if settings.auth_mode == "local":
        if username != settings.bind_username or password != settings.bind_password:
            raise ValueError("用户名或密码错误")
        return BoundUser(username=username, subject=f"local:{username}")

    if settings.auth_mode == "homeassistant":
        try:
            ok = await ha_client.validate_user_credentials(username, password, settings.app_base_url)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Home Assistant 登录请求失败: {exc}") from exc
        if not ok:
            raise ValueError("用户名或密码错误")
        return BoundUser(username=username, subject=f"ha:{username}")

    raise ValueError(f"unsupported auth mode: {settings.auth_mode}")
