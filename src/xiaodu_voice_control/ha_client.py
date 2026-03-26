from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class HomeAssistantClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._access_token = settings.ha_access_token

    def _base_url(self) -> str:
        base_url = str(self._settings.ha_base_url or "").rstrip("/")
        if not base_url:
            raise RuntimeError("HA_BASE_URL is not configured")
        return base_url

    async def _ensure_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        if not self._settings.ha_refresh_token or not self._settings.ha_client_id:
            raise RuntimeError("HA access token or refresh token/client id is required")
        base_url = self._base_url()
        async with httpx.AsyncClient(verify=self._settings.ha_verify_ssl, timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/auth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._settings.ha_client_id,
                    "refresh_token": self._settings.ha_refresh_token,
                },
            )
            response.raise_for_status()
            result = response.json()
            self._access_token = result["access_token"]
            return self._access_token

    async def _headers(self) -> dict[str, str]:
        token = await self._ensure_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        headers = await self._headers()
        base_url = self._base_url()
        async with httpx.AsyncClient(verify=self._settings.ha_verify_ssl, timeout=10.0) as client:
            response = await client.get(
                f"{base_url}/api/states/{entity_id}",
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        headers = await self._headers()
        base_url = self._base_url()
        async with httpx.AsyncClient(verify=self._settings.ha_verify_ssl, timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/api/services/{domain}/{service}",
                headers=headers,
                json=data,
            )
            response.raise_for_status()
            return response.json()

    async def validate_user_credentials(self, username: str, password: str, app_base_url: str) -> bool:
        base_url = self._base_url()
        if not app_base_url:
            raise RuntimeError("APP_BASE_URL is not configured")
        login_flow_payload = {
            "client_id": app_base_url,
            "handler": ["homeassistant", None],
            "redirect_uri": app_base_url + "/auth/callback",
            "type": "authorize",
        }
        async with httpx.AsyncClient(verify=self._settings.ha_verify_ssl, timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/auth/login_flow",
                json=login_flow_payload,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code >= 400:
                raise RuntimeError(f"HA login_flow start failed: {response.status_code} {response.text[:200]}")
            response.raise_for_status()
            flow = response.json()
            flow_id = flow.get("flow_id")
            if not flow_id:
                return False
            login_payload = {
                "client_id": app_base_url,
                "username": username,
                "password": password,
            }
            response = await client.post(
                f"{base_url}/auth/login_flow/{flow_id}",
                json=login_payload,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code in (400, 401, 403):
                return False
            if response.status_code >= 400:
                raise RuntimeError(f"HA login_flow submit failed: {response.status_code} {response.text[:200]}")
            response.raise_for_status()
            result = response.json()
            return bool(result.get("result"))
