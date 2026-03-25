from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import secrets
import threading

from .config import Settings


@dataclass(slots=True)
class AuthorizationCodeRecord:
    code: str
    subject: str
    username: str
    client_id: str
    redirect_uri: str
    expires_at: str


@dataclass(slots=True)
class AccessTokenRecord:
    access_token: str
    refresh_token: str
    subject: str
    username: str
    client_id: str
    expires_at: str
    refresh_expires_at: str


@dataclass(slots=True)
class XiaoDuLinkRecord:
    client_id: str
    open_uid: str
    bot_id: str
    username: str
    subject: str
    updated_at: str


class TokenStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = Path(settings.token_store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = {
            "authorization_codes": {},
            "access_tokens": {},
            "refresh_tokens": {},
            "links": {},
            "service_config": {
                "xiaodu_skill_id": "",
                "xiaodu_client_secret": "",
                "internal_api_token": "",
                "open_uids": [],
                "updated_at": "",
            },
        }
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._lock:
            # Tolerate UTF-8 BOM in manually edited/imported token store files.
            self._data = json.loads(self._path.read_text(encoding="utf-8-sig"))
            self._data.setdefault(
                "service_config",
                {
                    "xiaodu_skill_id": "",
                    "xiaodu_client_secret": "",
                    "internal_api_token": "",
                    "open_uids": [],
                    "updated_at": "",
                },
            )
            self._cleanup_locked()

    def _save_locked(self) -> None:
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _iso(self, dt: datetime) -> str:
        return dt.isoformat()

    def _is_expired(self, value: str) -> bool:
        return datetime.fromisoformat(value) <= self._now()

    def _cleanup_locked(self) -> None:
        self._data["authorization_codes"] = {
            code: record
            for code, record in self._data["authorization_codes"].items()
            if not self._is_expired(record["expires_at"])
        }
        self._data["access_tokens"] = {
            token: record
            for token, record in self._data["access_tokens"].items()
            if not self._is_expired(record["expires_at"])
        }
        self._data["refresh_tokens"] = {
            token: record
            for token, record in self._data["refresh_tokens"].items()
            if not self._is_expired(record["refresh_expires_at"])
        }
        self._save_locked()

    def issue_authorization_code(self, subject: str, username: str, client_id: str, redirect_uri: str) -> str:
        with self._lock:
            self._cleanup_locked()
            code = secrets.token_urlsafe(32)
            record = AuthorizationCodeRecord(
                code=code,
                subject=subject,
                username=username,
                client_id=client_id,
                redirect_uri=redirect_uri,
                expires_at=self._iso(self._now() + timedelta(seconds=self._settings.authorization_code_ttl_seconds)),
            )
            self._data["authorization_codes"][code] = asdict(record)
            self._save_locked()
            return code

    def consume_authorization_code(self, code: str, client_id: str, redirect_uri: str) -> AuthorizationCodeRecord | None:
        with self._lock:
            self._cleanup_locked()
            record = self._data["authorization_codes"].pop(code, None)
            self._save_locked()
            if not record:
                return None
            if record["client_id"] != client_id or record["redirect_uri"] != redirect_uri:
                return None
            return AuthorizationCodeRecord(**record)

    def issue_token_pair(self, subject: str, username: str, client_id: str) -> AccessTokenRecord:
        with self._lock:
            self._cleanup_locked()
            access_token = secrets.token_urlsafe(48)
            refresh_token = secrets.token_urlsafe(64)
            record = AccessTokenRecord(
                access_token=access_token,
                refresh_token=refresh_token,
                subject=subject,
                username=username,
                client_id=client_id,
                expires_at=self._iso(self._now() + timedelta(seconds=self._settings.access_token_ttl_seconds)),
                refresh_expires_at=self._iso(self._now() + timedelta(seconds=self._settings.refresh_token_ttl_seconds)),
            )
            self._data["access_tokens"][access_token] = asdict(record)
            self._data["refresh_tokens"][refresh_token] = asdict(record)
            self._save_locked()
            return record

    def refresh_access_token(self, refresh_token: str, client_id: str) -> AccessTokenRecord | None:
        with self._lock:
            self._cleanup_locked()
            record = self._data["refresh_tokens"].get(refresh_token)
            if not record or record["client_id"] != client_id:
                return None
            self._data["access_tokens"] = {
                token: access
                for token, access in self._data["access_tokens"].items()
                if access["refresh_token"] != refresh_token
            }
            new_token = secrets.token_urlsafe(48)
            new_record = AccessTokenRecord(
                access_token=new_token,
                refresh_token=refresh_token,
                subject=record["subject"],
                username=record["username"],
                client_id=client_id,
                expires_at=self._iso(self._now() + timedelta(seconds=self._settings.access_token_ttl_seconds)),
                refresh_expires_at=record["refresh_expires_at"],
            )
            self._data["access_tokens"][new_token] = asdict(new_record)
            self._data["refresh_tokens"][refresh_token] = asdict(new_record)
            self._save_locked()
            return new_record

    def validate_access_token(self, access_token: str) -> AccessTokenRecord | None:
        with self._lock:
            self._cleanup_locked()
            record = self._data["access_tokens"].get(access_token)
            if not record:
                return None
            return AccessTokenRecord(**record)

    def upsert_link(
        self,
        *,
        client_id: str,
        open_uid: str,
        bot_id: str,
        username: str,
        subject: str,
    ) -> XiaoDuLinkRecord:
        with self._lock:
            key = f"{client_id}:{open_uid}"
            record = XiaoDuLinkRecord(
                client_id=client_id,
                open_uid=open_uid,
                bot_id=bot_id,
                username=username,
                subject=subject,
                updated_at=self._iso(self._now()),
            )
            self._data.setdefault("links", {})[key] = asdict(record)
            self._save_locked()
            return record

    def list_links(self, client_id: str | None = None) -> list[XiaoDuLinkRecord]:
        with self._lock:
            links = []
            for record in self._data.get("links", {}).values():
                if client_id is not None and record.get("client_id") != client_id:
                    continue
                links.append(XiaoDuLinkRecord(**record))
            return links

    def get_service_config(self) -> dict:
        with self._lock:
            config = dict(self._data.get("service_config", {}) or {})
            config.setdefault("xiaodu_skill_id", "")
            config.setdefault("xiaodu_client_secret", "")
            config.setdefault("internal_api_token", "")
            config.setdefault("open_uids", [])
            config.setdefault("updated_at", "")
            return config

    def get_legacy_devices(self) -> list[dict]:
        with self._lock:
            devices = self._data.get("devices", []) or []
            return [dict(device) for device in devices]

    def clear_legacy_devices(self) -> None:
        with self._lock:
            if "devices" in self._data:
                self._data.pop("devices", None)
                self._save_locked()

    def update_service_config(
        self,
        *,
        xiaodu_skill_id: str | None = None,
        xiaodu_client_secret: str | None = None,
        internal_api_token: str | None = None,
        open_uids: list[str] | None = None,
    ) -> dict:
        with self._lock:
            config = self.get_service_config()
            if xiaodu_skill_id is not None:
                config["xiaodu_skill_id"] = xiaodu_skill_id.strip()
            if xiaodu_client_secret is not None:
                config["xiaodu_client_secret"] = xiaodu_client_secret.strip()
            if internal_api_token is not None:
                config["internal_api_token"] = internal_api_token.strip()
            if open_uids is not None:
                merged = [str(item).strip() for item in open_uids if str(item).strip()]
                config["open_uids"] = list(dict.fromkeys(merged))
            config["updated_at"] = self._iso(self._now())
            self._data["service_config"] = config
            self._save_locked()
            return dict(config)
