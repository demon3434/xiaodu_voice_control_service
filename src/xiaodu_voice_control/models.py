from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


DEFAULT_CAPABILITIES: dict[str, dict[str, list[str]]] = {
    "switch": {
        "actions": ["turnOn", "turnOff"],
        "properties": ["turnOnState"],
    },
    "light": {
        "actions": ["turnOn", "turnOff", "setBrightnessPercentage"],
        "properties": ["turnOnState", "brightness"],
    },
    "cover": {
        "actions": ["turnOn", "turnOff", "pause"],
        "properties": ["turnOnState", "openPercent"],
    },
    "fan": {
        "actions": ["turnOn", "turnOff"],
        "properties": ["turnOnState"],
    },
    "climate": {
        "actions": ["turnOn", "turnOff", "setTemperature", "incrementTemperature", "decrementTemperature"],
        "properties": ["turnOnState", "temperatureReading", "humidity"],
    },
    "sensor": {
        "actions": [],
        "properties": ["temperatureReading", "humidity", "brightness", "pm25", "pm10", "co2"],
    },
}


class DeviceConfig(BaseModel):
    appliance_id: str
    name: str
    type: str
    entity_id: str
    actions: list[str] = Field(default_factory=list)
    properties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_capabilities(self) -> "DeviceConfig":
        device_type = str(self.type or "").strip().lower()
        defaults = DEFAULT_CAPABILITIES.get(device_type)
        if not defaults:
            return self

        if not self.actions:
            self.actions = list(defaults["actions"])
        if not self.properties:
            self.properties = list(defaults["properties"])

        self.actions = list(dict.fromkeys(self.actions))
        self.properties = list(dict.fromkeys(self.properties))
        return self


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


class HaAuthCandidate(BaseModel):
    token: str
    client_id: str
    title: str
    user_label: str = ""
    last_used_at: str = ""
    created_at: str = ""
    token_type: str = ""
