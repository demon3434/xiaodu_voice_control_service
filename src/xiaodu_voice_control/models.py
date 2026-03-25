from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DeviceConfig(BaseModel):
    appliance_id: str
    name: str
    type: str
    entity_id: str
    actions: list[str] = Field(default_factory=list)
    properties: list[str] = Field(default_factory=list)


class DeviceConfigFile(BaseModel):
    devices: list[DeviceConfig] = Field(default_factory=list)


class OAuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str | None = None


class HaState(BaseModel):
    entity_id: str
    state: str
    attributes: dict[str, Any] = Field(default_factory=dict)
