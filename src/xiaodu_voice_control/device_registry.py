from __future__ import annotations

from pathlib import Path

import yaml

from .models import DeviceConfig, DeviceConfigFile


class DeviceRegistry:
    def __init__(self, config_path: str) -> None:
        self._config_path = Path(config_path)
        self._devices_by_id: dict[str, DeviceConfig] = {}

    def load(self) -> None:
        if not self._config_path.exists():
            self._devices_by_id = {}
            self.save()
            return
        raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
        parsed = DeviceConfigFile.model_validate(raw)
        self._devices_by_id = {device.appliance_id: device for device in parsed.devices}

    def save(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "devices": [device.model_dump() for device in self.list_devices()],
        }
        self._config_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def list_devices(self) -> list[DeviceConfig]:
        return list(self._devices_by_id.values())

    def get(self, appliance_id: str) -> DeviceConfig:
        device = self._devices_by_id.get(appliance_id)
        if not device:
            raise KeyError(f"unknown appliance_id: {appliance_id}")
        return device

    def replace_devices(self, devices: list[DeviceConfig], *, persist: bool = True) -> None:
        self._devices_by_id = {device.appliance_id: device for device in devices}
        if persist:
            self.save()

