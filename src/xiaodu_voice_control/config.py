from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("/data/service.env", ".env"), env_file_encoding="utf-8")

    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8129, alias="APP_PORT")
    app_debug: bool = Field(default=False, alias="APP_DEBUG")
    app_base_url: str = Field(default="", alias="APP_BASE_URL")

    auth_mode: str = Field(default="homeassistant", alias="AUTH_MODE")
    bind_username: str = Field(default="admin", alias="BIND_USERNAME")
    bind_password: str = Field(default="change_me", alias="BIND_PASSWORD")

    ha_base_url: str = Field(default="", alias="HA_BASE_URL")
    ha_access_token: str = Field(default="", alias="HA_ACCESS_TOKEN")
    ha_refresh_token: str = Field(default="", alias="HA_REFRESH_TOKEN")
    ha_client_id: str = Field(default="", alias="HA_CLIENT_ID")
    ha_verify_ssl: bool = Field(default=True, alias="HA_VERIFY_SSL")

    xiaodu_client_id: str = Field(default="dueros", alias="XIAODU_CLIENT_ID")
    xiaodu_client_secret: str = Field(default="", alias="XIAODU_CLIENT_SECRET")
    xiaodu_skill_id: str = Field(default="", alias="XIAODU_SKILL_ID")
    xiaodu_allowed_redirect_uris: str = Field(
        default="https://xiaodu.baidu.com/saiya/auth/,https://xiaodu-dbp.baidu.com/saiya/auth/",
        alias="XIAODU_ALLOWED_REDIRECT_URIS",
    )
    xiaodu_private_key_path: str = Field(default="/data/xiaodu_private_key.pem", alias="XIAODU_PRIVATE_KEY_PATH")
    xiaodu_sync_stage: str = Field(default="debug", alias="XIAODU_SYNC_STAGE")
    internal_api_token: str = Field(default="", alias="INTERNAL_API_TOKEN")

    device_config_path: str = Field(default="/data/devices.yaml", alias="DEVICE_CONFIG_PATH")
    token_store_path: str = Field(default="/data/token_store.json", alias="TOKEN_STORE_PATH")
    service_env_path: str = Field(default="/data/service.env", alias="SERVICE_ENV_PATH")
    access_token_ttl_seconds: int = Field(default=86400, alias="ACCESS_TOKEN_TTL_SECONDS")
    authorization_code_ttl_seconds: int = Field(default=300, alias="AUTHORIZATION_CODE_TTL_SECONDS")
    refresh_token_ttl_seconds: int = Field(default=2592000, alias="REFRESH_TOKEN_TTL_SECONDS")

    @property
    def allowed_redirect_uris(self) -> set[str]:
        return {item.strip() for item in self.xiaodu_allowed_redirect_uris.split(",") if item.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
