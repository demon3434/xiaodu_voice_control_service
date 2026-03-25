from __future__ import annotations

from pathlib import Path
import asyncio
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .config import Settings


MANAGED_ENV_KEYS = [
    "APP_BASE_URL",
    "HA_BASE_URL",
    "HA_REFRESH_TOKEN",
    "HA_CLIENT_ID",
    "INTERNAL_API_TOKEN",
]


def _parse_env_lines(text: str) -> tuple[list[str], dict[str, str]]:
    lines = text.splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def load_managed_env(settings: Settings) -> dict[str, str]:
    path = Path(settings.service_env_path)
    if path.exists():
        _, values = _parse_env_lines(path.read_text(encoding="utf-8"))
    else:
        values = {}
    defaults = {
        "APP_BASE_URL": settings.app_base_url,
        "HA_BASE_URL": settings.ha_base_url,
        "HA_REFRESH_TOKEN": settings.ha_refresh_token,
        "HA_CLIENT_ID": settings.ha_client_id,
        "INTERNAL_API_TOKEN": settings.internal_api_token,
    }
    return {key: str(values.get(key, defaults.get(key, ""))) for key in MANAGED_ENV_KEYS}


def save_managed_env(settings: Settings, updates: dict[str, str]) -> dict[str, str]:
    path = Path(settings.service_env_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        lines, current = _parse_env_lines(path.read_text(encoding="utf-8"))
    else:
        lines, current = [], {}
    merged = dict(current)
    for key in MANAGED_ENV_KEYS:
        if key in updates:
            merged[key] = str(updates[key]).strip()
    output_lines: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            output_lines.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in MANAGED_ENV_KEYS:
            output_lines.append(f"{key}={merged.get(key, '')}")
            seen.add(key)
        else:
            output_lines.append(line)
    for key in MANAGED_ENV_KEYS:
        if key not in seen:
            output_lines.append(f"{key}={merged.get(key, '')}")
    path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")
    return {key: merged.get(key, "") for key in MANAGED_ENV_KEYS}


def key_status(settings: Settings) -> dict[str, str | bool]:
    private_path = Path(settings.xiaodu_private_key_path)
    public_path = private_path.with_name("xiaodu_public_key.pem")
    public_key_pem = public_path.read_text(encoding="utf-8") if public_path.exists() else ""
    return {
        "private_key_path": str(private_path),
        "public_key_path": str(public_path),
        "private_key_exists": private_path.exists(),
        "public_key_exists": public_path.exists(),
        "public_key_pem": public_key_pem,
    }


def generate_keypair(settings: Settings, force: bool = False) -> dict[str, str | bool]:
    private_path = Path(settings.xiaodu_private_key_path)
    public_path = private_path.with_name("xiaodu_public_key.pem")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    if private_path.exists() and not force:
        return {
            **key_status(settings),
            "status": "exists",
        }
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return {
        **key_status(settings),
        "status": "generated",
        "public_key_pem": public_path.read_text(encoding="utf-8"),
    }


async def delayed_process_exit(delay_seconds: float = 1.0) -> None:
    await asyncio.sleep(delay_seconds)
    os._exit(0)


async def delayed_process_reload(settings: Settings, delay_seconds: float = 1.0) -> None:
    await asyncio.sleep(delay_seconds)
    runtime_env = os.environ.copy()
    runtime_env.update(load_managed_env(settings))
    os.execvpe(
        "sh",
        [
            "sh",
            "-c",
            "python -m xiaodu_voice_control.bootstrap && uvicorn xiaodu_voice_control.app:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8129}",
        ],
        runtime_env,
    )
