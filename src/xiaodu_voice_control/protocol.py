from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from .models import DeviceConfig


DEVICE_TYPE_MAP = {
    "switch": "SWITCH",
    "light": "LIGHT",
    "cover": "CURTAIN",
    "sensor": "AIR_MONITOR",
    "fan": "FAN",
    "climate": "AIR_CONDITION",
}

DISCOVERY_QUERY_ACTIONS = {
    "turnOnState": "getTurnOnState",
    "temperatureReading": "getTemperatureReading",
    "humidity": "getHumidity",
    "brightness": "getBrightnessPercentage",
    "openPercent": "getState",
    "pm25": "getAirPM25",
    "pm10": "getAirPM10",
    "co2": "getCO2Quantity",
}

QUERY_NAME_TO_PROPERTY = {
    "GetTurnOnStateRequest": "turnOnState",
    "GetTemperatureReadingRequest": "temperatureReading",
    "GetHumidityRequest": "humidity",
    "GetBrightnessPercentageRequest": "brightness",
    "GetAirPM25Request": "pm25",
    "GetAirPM10Request": "pm10",
    "GetCO2QuantityRequest": "co2",
}


@dataclass(slots=True)
class ServiceCall:
    domain: str
    service: str
    data: dict[str, Any]


def build_response_header(request_body: dict[str, Any], name: str) -> dict[str, Any]:
    header = dict(request_body.get("header", {}))
    header["name"] = name
    header.setdefault("payloadVersion", "1")
    return header


def error_response(request_body: dict[str, Any], error_name: str) -> dict[str, Any]:
    return {
        "header": build_response_header(request_body, error_name),
        "payload": {},
    }


def default_actions(device: DeviceConfig) -> list[str]:
    actions = list(device.actions)
    if device.type == "light" and "setBrightnessPercentage" not in actions:
        actions.append("setBrightnessPercentage")
    for prop in device.properties:
        query_action = DISCOVERY_QUERY_ACTIONS.get(prop)
        if query_action and query_action not in actions:
            actions.append(query_action)
    if device.type == "sensor" and "getState" not in actions:
        actions.append("getState")
    return actions


def _numeric(value: Any) -> int | float:
    if isinstance(value, (int, float)):
        return value
    if value is None:
        return 0
    text = str(value).strip().lower().replace("%", "").replace("℃", "").replace("°c", "")
    if text in {"unknown", "unavailable", "none", ""}:
        return 0
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return 0


def _rounded_numeric(value: Any, digits: int = 1) -> int | float:
    numeric = _numeric(value)
    if isinstance(numeric, float):
        return float(f"{numeric:.{digits}f}")
    return numeric


def state_to_property(property_name: str, state: dict[str, Any]) -> dict[str, Any]:
    raw_state = state.get("state")
    attrs = state.get("attributes", {})
    ts = int(time.time())

    if property_name == "turnOnState":
        value = "ON" if str(raw_state).lower() in {"on", "open", "opening", "true"} else "OFF"
        scale = ""
    elif property_name == "temperatureReading":
        value = _rounded_numeric(attrs.get("current_temperature", raw_state), 1)
        scale = "CELSIUS"
    elif property_name == "humidity":
        value = int(round(_numeric(attrs.get("current_humidity", attrs.get("humidity", raw_state)))))
        scale = "%"
    elif property_name == "brightness":
        brightness = attrs.get("brightness")
        if brightness is not None:
            value = round((_numeric(brightness) / 255) * 100, 2)
            scale = "%"
        else:
            value = _numeric(raw_state)
            scale = "%"
    elif property_name == "openPercent":
        value = _numeric(attrs.get("current_position", 100 if str(raw_state).lower() == "open" else 0))
        scale = "%"
    elif property_name == "pm25":
        value = _numeric(raw_state)
        scale = "μg/m3"
    elif property_name == "pm10":
        value = _numeric(raw_state)
        scale = "μg/m3"
    elif property_name == "co2":
        value = _numeric(raw_state)
        scale = "ppm"
    else:
        value = raw_state
        scale = ""

    return {
        "name": property_name,
        "value": value,
        "scale": scale,
        "timestampOfSample": ts,
        "uncertaintyInMilliseconds": 1000,
    }


def build_discovery_appliance(device: DeviceConfig, state: dict[str, Any] | None = None) -> dict[str, Any]:
    properties = []
    for prop in device.properties:
        if state is not None:
            properties.append(state_to_property(prop, state))
    return {
        "applianceId": device.appliance_id,
        "friendlyName": device.name,
        "friendlyDescription": device.name,
        "additionalApplianceDetails": {},
        "applianceTypes": [DEVICE_TYPE_MAP.get(device.type, device.type.upper())],
        "isReachable": True,
        "manufacturerName": "Custom",
        "modelName": "Home Assistant",
        "version": "1.0",
        "actions": default_actions(device),
        "attributes": properties,
    }


def resolve_service_call(device: DeviceConfig, request_name: str, payload: dict[str, Any]) -> ServiceCall:
    domain, _ = device.entity_id.split(".", 1)

    if request_name == "TurnOnRequest":
        service = "open_cover" if device.type == "cover" else "turn_on"
        return ServiceCall(domain=domain, service=service, data={"entity_id": device.entity_id})

    if request_name == "TurnOffRequest":
        service = "close_cover" if device.type == "cover" else "turn_off"
        return ServiceCall(domain=domain, service=service, data={"entity_id": device.entity_id})

    if request_name == "PauseRequest" and device.type == "cover":
        return ServiceCall(domain=domain, service="stop_cover", data={"entity_id": device.entity_id})

    if request_name == "SetBrightnessPercentageRequest" and device.type == "light":
        brightness = payload.get("brightness", {}).get("value", 0)
        return ServiceCall(domain=domain, service="turn_on", data={"entity_id": device.entity_id, "brightness_pct": brightness})

    raise ValueError(f"unsupported request for device: {request_name}")


def query_properties_for_request(device: DeviceConfig, request_name: str) -> list[str]:
    if request_name == "GetStateRequest":
        return list(device.properties)
    prop = QUERY_NAME_TO_PROPERTY.get(request_name)
    if not prop:
        raise ValueError(f"unsupported query request: {request_name}")
    if prop not in device.properties:
        raise ValueError(f"property not exposed: {prop}")
    return [prop]
