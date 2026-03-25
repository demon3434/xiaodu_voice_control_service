from __future__ import annotations

from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .config import get_settings


def ensure_runtime_files() -> None:
    settings = get_settings()

    private_key_path = Path(settings.xiaodu_private_key_path)
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    if not private_key_path.exists():
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        private_key_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    device_config_path = Path(settings.device_config_path)
    device_config_path.parent.mkdir(parents=True, exist_ok=True)
    if not device_config_path.exists():
        device_config_path.write_text(
            yaml.safe_dump({"devices": []}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


if __name__ == "__main__":
    ensure_runtime_files()
