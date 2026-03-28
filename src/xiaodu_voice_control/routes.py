from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from fastapi import APIRouter, Form, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from .auth import validate_bind_user
from .config import Settings
from .device_registry import DeviceRegistry
from .ha_client import HomeAssistantClient
from .management import delayed_process_reload, generate_keypair, key_status, load_managed_env, save_managed_env
from .models import DeviceConfig, DeviceConfigFile
from .protocol import (
    build_discovery_appliance,
    build_response_header,
    error_response,
    query_properties_for_request,
    resolve_service_call,
    state_to_property,
)
from .token_store import TokenStore


ATTRIBUTE_LIST_QUERY_RESPONSES = {
    "GetHumidityRequest",
    "GetTargetHumidityRequest",
}


def _load_login_html() -> str:
    template_path = Path(__file__).resolve().parent / "templates" / "login.html"
    return template_path.read_text(encoding="utf-8")


def _load_manage_html() -> str:
    template_path = Path(__file__).resolve().parent / "templates" / "manage.html"
    return template_path.read_text(encoding="utf-8")


def _runtime_client_secret(settings: Settings, token_store: TokenStore) -> str:
    return str(token_store.get_service_config().get("xiaodu_client_secret") or settings.xiaodu_client_secret).strip()


def _missing_runtime_fields(settings: Settings, token_store: TokenStore) -> list[str]:
    config = token_store.get_service_config()
    missing: list[str] = []
    if not str(settings.ha_base_url or "").strip():
        missing.append("HA_BASE_URL")
    if not (str(settings.ha_access_token or "").strip() or (str(settings.ha_refresh_token or "").strip() and str(settings.ha_client_id or "").strip())):
        missing.append("HA_ACCESS_TOKEN or HA_REFRESH_TOKEN+HA_CLIENT_ID")
    if settings.auth_mode == "homeassistant" and not str(settings.app_base_url or "").strip():
        missing.append("APP_BASE_URL")
    if not _runtime_client_secret(settings, token_store):
        missing.append("xiaodu_client_secret(runtime)")
    return missing


def _token_response(record, expires_in: int) -> dict:
    return {
        "access_token": record.access_token,
        "refresh_token": record.refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


def _validate_internal_token(settings: Settings, token_store: TokenStore, token: str | None) -> None:
    runtime_token = str(token_store.get_service_config().get("internal_api_token", "")).strip()
    expected = runtime_token or settings.internal_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="internal api token not configured")
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid internal api token")


def _validate_client_runtime(
    settings: Settings,
    token_store: TokenStore,
    client_id: str,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> None:
    if client_id != settings.xiaodu_client_id:
        raise ValueError("invalid client_id")
    runtime_secret = _runtime_client_secret(settings, token_store)
    if client_secret is not None and client_secret != runtime_secret:
        raise ValueError("invalid client_secret")
    if redirect_uri:
        allowed = False
        for item in settings.allowed_redirect_uris:
            normalized = item.strip()
            if not normalized:
                continue
            if normalized.endswith("*"):
                if redirect_uri.startswith(normalized[:-1]):
                    allowed = True
                    break
                continue
            if normalized.endswith("/"):
                if redirect_uri.startswith(normalized):
                    allowed = True
                    break
                continue
            if redirect_uri == normalized:
                allowed = True
                break
        if not allowed:
            raise ValueError("invalid redirect_uri")


async def _sync_xiaodu_cloud(
    settings: Settings,
    token_store: TokenStore,
) -> dict:
    runtime_config = token_store.get_service_config()
    skill_id = str(runtime_config.get("xiaodu_skill_id") or settings.xiaodu_skill_id).strip()
    if not skill_id:
        return {
            "status": "skipped",
            "reason": "missing xiaodu skill id",
            "results": [],
        }

    links = token_store.list_links(settings.xiaodu_client_id)
    grouped: dict[str, list[str]] = {}
    for link in links:
        current_bot_id = link.bot_id or skill_id
        if not current_bot_id or not link.open_uid:
            continue
        grouped.setdefault(current_bot_id, [])
        if link.open_uid not in grouped[current_bot_id]:
            grouped[current_bot_id].append(link.open_uid)

    if not grouped:
        for open_uid in runtime_config.get("open_uids", []) or []:
            if not open_uid:
                continue
            grouped.setdefault(skill_id, [])
            if open_uid not in grouped[skill_id]:
                grouped[skill_id].append(open_uid)

    if not grouped:
        return {"status": "skipped", "reason": "no linked xiaodu users", "results": []}

    key_path = Path(settings.xiaodu_private_key_path)
    if not key_path.exists():
        return {"status": "skipped", "reason": f"missing private key: {key_path}", "results": []}
    private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)

    results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for bot_id, open_uids in grouped.items():
            payload = {
                "botId": bot_id or skill_id,
                "logId": __import__("uuid").uuid4().hex,
                "openUids": open_uids[:5],
            }
            body_bytes = httpx.Request("POST", "https://xiaodu.baidu.com/saiya/smarthome/devicesync", json=payload).content
            timestamp = str(int(__import__("time").time()))
            sign_source = (
                base64.b64encode(body_bytes).decode("utf-8")
                + (bot_id or skill_id)
                + timestamp
                + settings.xiaodu_sync_stage
            )
            signature = base64.b64encode(
                private_key.sign(
                    sign_source.encode("utf-8"),
                    padding.PKCS1v15(),
                    hashes.SHA1(),
                )
            ).decode("utf-8")
            response = await client.post(
                "https://xiaodu.baidu.com/saiya/smarthome/devicesync",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "timestamp": timestamp,
                    "signature": signature,
                },
            )
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text}
            results.append(
                {
                    "bot_id": bot_id,
                    "open_uids": open_uids[:5],
                    "status_code": response.status_code,
                    "response": body,
                }
            )
    return {"status": "ok", "results": results}


async def _fetch_state_with_retry(
    ha_client: HomeAssistantClient,
    entity_id: str,
    expected_state: str | None = None,
    retries: int = 5,
    delay: float = 0.4,
) -> dict:
    last_state = {}
    for _ in range(retries):
        last_state = await ha_client.get_state(entity_id)
        if expected_state is None or str(last_state.get("state", "")).lower() == expected_state.lower():
            return last_state
        await asyncio.sleep(delay)
    return last_state


def build_router(
    settings: Settings,
    registry: DeviceRegistry,
    ha_client: HomeAssistantClient,
    token_store: TokenStore,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        missing = _missing_runtime_fields(settings, token_store)
        if missing:
            return {"status": "degraded", "missing": ",".join(missing)}
        return {"status": "ok"}

    @router.get("/", response_class=HTMLResponse)
    async def root_page() -> HTMLResponse:
        return HTMLResponse(content=_load_manage_html())

    @router.get("/manage", response_class=HTMLResponse)
    async def manage_page() -> HTMLResponse:
        return HTMLResponse(content=_load_manage_html())

    @router.get("/manage/api/config")
    async def manage_get_config() -> dict:
        return {
            "env": load_managed_env(settings),
            "keys": key_status(settings),
            "devices": {
                "count": len(registry.list_devices()),
                "path": settings.device_config_path,
            },
        }

    @router.get("/manage/api/keys/public")
    async def manage_download_public_key():
        public_path = Path(settings.xiaodu_private_key_path).with_name("xiaodu_public_key.pem")
        if not public_path.exists():
            raise HTTPException(status_code=404, detail="public key not found")
        return FileResponse(
            path=str(public_path),
            media_type="application/x-pem-file",
            filename="xiaodu_public_key.pem",
        )

    @router.post("/manage/api/config")
    async def manage_save_config(request: Request) -> dict:
        payload = await request.json()
        saved = save_managed_env(settings, payload.get("env") or {})
        return {
            "status": "ok",
            "env": saved,
            "keys": key_status(settings),
            "message": "已写入 service.env，点击“重新加载配置”后生效。",
        }

    @router.post("/manage/api/keys/generate")
    async def manage_generate_keys(request: Request) -> dict:
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        result = generate_keypair(settings, force=bool(payload.get("force")))
        return result

    @router.post("/manage/api/reload")
    async def manage_reload() -> dict:
        asyncio.create_task(delayed_process_reload(settings))
        return {"status": "ok", "message": "服务正在重新加载配置，新的 service.env 和密钥将立即生效。"}

    @router.get("/devices")
    async def list_devices(x_internal_token: str | None = Header(default=None)) -> dict:
        _validate_internal_token(settings, token_store, x_internal_token)
        return {"devices": [device.model_dump() for device in registry.list_devices()]}

    @router.get("/internal/devices")
    async def internal_list_devices(x_internal_token: str | None = Header(default=None)) -> dict:
        _validate_internal_token(settings, token_store, x_internal_token)
        return {"devices": [device.model_dump() for device in registry.list_devices()]}

    @router.put("/internal/devices")
    async def internal_replace_devices(
        payload: DeviceConfigFile,
        x_internal_token: str | None = Header(default=None),
    ) -> dict:
        _validate_internal_token(settings, token_store, x_internal_token)
        registry.replace_devices(payload.devices)
        return {
            "status": "ok",
            "count": len(payload.devices),
            "devices": [device.model_dump() for device in registry.list_devices()],
        }

    @router.post("/internal/reload")
    async def internal_reload(x_internal_token: str | None = Header(default=None)) -> dict:
        _validate_internal_token(settings, token_store, x_internal_token)
        registry.load()
        return {
            "status": "ok",
            "count": len(registry.list_devices()),
        }

    @router.post("/internal/device-sync")
    async def internal_device_sync(x_internal_token: str | None = Header(default=None)) -> dict:
        _validate_internal_token(settings, token_store, x_internal_token)
        return await _sync_xiaodu_cloud(settings, token_store)

    @router.get("/internal/settings")
    async def internal_get_settings(x_internal_token: str | None = Header(default=None)) -> dict:
        _validate_internal_token(settings, token_store, x_internal_token)
        config = token_store.get_service_config()
        linked_open_uids = []
        for link in token_store.list_links(settings.xiaodu_client_id):
            if link.open_uid not in linked_open_uids:
                linked_open_uids.append(link.open_uid)
        open_uids = linked_open_uids or list(config.get("open_uids") or [])
        if open_uids != list(config.get("open_uids") or []):
            config = token_store.update_service_config(open_uids=open_uids)
        return config

    @router.put("/internal/settings")
    async def internal_put_settings(
        payload: dict,
        x_internal_token: str | None = Header(default=None),
    ) -> dict:
        _validate_internal_token(settings, token_store, x_internal_token)
        skill_id = str(payload.get("xiaodu_skill_id", "")).strip()
        client_secret = str(payload.get("xiaodu_client_secret", "")).strip()
        internal_api_token = str(payload.get("internal_api_token", "")).strip()
        open_uids = [str(item).strip() for item in (payload.get("open_uids") or []) if str(item).strip()]
        config = token_store.update_service_config(
            xiaodu_skill_id=skill_id,
            xiaodu_client_secret=client_secret,
            internal_api_token=internal_api_token,
            open_uids=open_uids,
        )
        token_store.replace_links(
            client_id=settings.xiaodu_client_id,
            open_uids=open_uids,
            bot_id=skill_id,
        )
        linked_open_uids = []
        for link in token_store.list_links(settings.xiaodu_client_id):
            if skill_id and link.bot_id != skill_id:
                token_store.upsert_link(
                    client_id=link.client_id,
                    open_uid=link.open_uid,
                    bot_id=skill_id,
                    username=link.username,
                    subject=link.subject,
                )
            if link.open_uid not in linked_open_uids:
                linked_open_uids.append(link.open_uid)
        if linked_open_uids:
            return token_store.update_service_config(open_uids=linked_open_uids)
        return config

    @router.get("/xiaoduvc/auth/authorize", response_class=HTMLResponse)
    @router.get("/oauth/authorize", response_class=HTMLResponse)
    async def authorize_page(client_id: str, redirect_uri: str, response_type: str = "code", state: str | None = None) -> HTMLResponse:
        try:
            _validate_client_runtime(settings, token_store, client_id, redirect_uri=redirect_uri)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if response_type != "code":
            raise HTTPException(status_code=400, detail="unsupported response_type")
        body = _load_login_html().replace("__CLIENT_ID__", client_id).replace("__STATE__", state or "")
        return HTMLResponse(content=body)

    @router.post("/xiaoduvc/auth/authorize")
    @router.post("/oauth/authorize")
    async def authorize_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> dict:
        client_id = request.query_params.get("client_id", "")
        redirect_uri = request.query_params.get("redirect_uri", "")
        state = request.query_params.get("state")
        response_type = request.query_params.get("response_type", "code")

        try:
            _validate_client_runtime(settings, token_store, client_id, redirect_uri=redirect_uri)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if response_type != "code":
            raise HTTPException(status_code=400, detail="unsupported response_type")

        try:
            bound_user = await validate_bind_user(settings, ha_client, username, password)
        except ValueError as exc:
            return {"code": "error", "Msg": str(exc)}
        except RuntimeError as exc:
            return {"code": "error", "Msg": str(exc)}
        except Exception as exc:  # pragma: no cover
            return {"code": "error", "Msg": f"授权服务异常: {exc}"}

        code = token_store.issue_authorization_code(
            subject=bound_user.subject,
            username=bound_user.username,
            client_id=client_id,
            redirect_uri=redirect_uri,
        )
        query = {"code": code}
        if state:
            query["state"] = state
        location = redirect_uri + ("&" if "?" in redirect_uri else "?") + urlencode(query)
        return {"code": "ok", "Msg": "成功授权", "data": {"location": location}}

    @router.post("/xiaoduvc/auth/token")
    @router.post("/oauth/token")
    async def issue_token(request: Request) -> dict:
        form = await request.form()
        grant_type = str(form.get("grant_type", ""))
        client_id = str(form.get("client_id", ""))
        client_secret = str(form.get("client_secret", ""))
        redirect_uri = str(form.get("redirect_uri", "")) or None
        try:
            _validate_client_runtime(settings, token_store, client_id, client_secret=client_secret, redirect_uri=redirect_uri)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        if grant_type == "authorization_code":
            code = str(form.get("code", ""))
            if not code or not redirect_uri:
                raise HTTPException(status_code=400, detail="missing code or redirect_uri")
            record = token_store.consume_authorization_code(code, client_id, redirect_uri)
            if not record:
                raise HTTPException(status_code=401, detail="invalid authorization code")
            token_record = token_store.issue_token_pair(record.subject, record.username, client_id)
            return _token_response(token_record, settings.access_token_ttl_seconds)

        if grant_type == "refresh_token":
            refresh_token = str(form.get("refresh_token", ""))
            if not refresh_token:
                raise HTTPException(status_code=400, detail="missing refresh_token")
            token_record = token_store.refresh_access_token(refresh_token, client_id)
            if not token_record:
                raise HTTPException(status_code=401, detail="invalid refresh_token")
            return _token_response(token_record, settings.access_token_ttl_seconds)

        raise HTTPException(status_code=400, detail="unsupported grant_type")

    @router.post("/xiaoduvc/service")
    async def havcs_service(request: Request) -> dict:
        body = await request.json()
        header = body.get("header", {})
        payload = body.get("payload", {})
        request_name = str(header.get("name", ""))
        namespace = str(header.get("namespace", ""))
        access_token = str(payload.get("accessToken", ""))

        token_record = token_store.validate_access_token(access_token)
        if not token_record:
            return error_response(body, "InvalidAccessTokenError")

        open_uid = str(payload.get("openUid", "")).strip()
        bot_id = str(token_store.get_service_config().get("xiaodu_skill_id") or settings.xiaodu_skill_id).strip()
        if open_uid:
            current_open_uids = list(token_store.get_service_config().get("open_uids") or [])
            if open_uid not in current_open_uids:
                current_open_uids.append(open_uid)
                token_store.update_service_config(open_uids=current_open_uids)
        if open_uid and bot_id:
            token_store.upsert_link(
                client_id=token_record.client_id,
                open_uid=open_uid,
                bot_id=bot_id,
                username=token_record.username,
                subject=token_record.subject,
            )

        if namespace == "DuerOS.ConnectedHome.Discovery":
            appliances = []
            for device in registry.list_devices():
                state = None
                try:
                    state = await ha_client.get_state(device.entity_id)
                except Exception:
                    state = None
                appliances.append(build_discovery_appliance(device, state))
            return {
                "header": build_response_header(body, "DiscoverAppliancesResponse"),
                "payload": {"discoveredAppliances": appliances},
            }

        if namespace == "DuerOS.ConnectedHome.Control":
            appliance = payload.get("appliance", {})
            appliance_id = appliance.get("applianceId")
            if not appliance_id:
                return error_response(body, "DriverInternalError")
            try:
                device = registry.get(appliance_id)
                call = resolve_service_call(device, request_name, payload)
                await ha_client.call_service(call.domain, call.service, call.data)
                expected_state = None
                if request_name == "TurnOnRequest":
                    expected_state = "open" if device.type == "cover" else "on"
                elif request_name == "TurnOffRequest":
                    expected_state = "closed" if device.type == "cover" else "off"
                state = await _fetch_state_with_retry(ha_client, device.entity_id, expected_state)
                attributes = [state_to_property(prop, state) for prop in device.properties]
                return {
                    "header": build_response_header(body, request_name.replace("Request", "Confirmation")),
                    "payload": {"attributes": attributes},
                }
            except KeyError:
                return error_response(body, "DriverInternalError")
            except ValueError:
                return error_response(body, "NotSupportedInCurrentModeError")
            except Exception:
                return error_response(body, "TargetConnectivityUnstableError")

        if namespace == "DuerOS.ConnectedHome.Query":
            appliance = payload.get("appliance", {})
            appliance_id = appliance.get("applianceId")
            if not appliance_id:
                return error_response(body, "DriverInternalError")
            try:
                device = registry.get(appliance_id)
                state = await ha_client.get_state(device.entity_id)
                props = query_properties_for_request(device, request_name)
                if request_name == "GetStateRequest":
                    attrs = [state_to_property(prop, state) for prop in props]
                    return {
                        "header": build_response_header(body, "GetStateResponse"),
                        "payload": {"attributes": attrs},
                    }
                prop = state_to_property(props[0], state)
                if request_name in ATTRIBUTE_LIST_QUERY_RESPONSES:
                    return {
                        "header": build_response_header(body, request_name.replace("Request", "Response")),
                        "payload": {"attributes": [prop]},
                    }
                return {
                    "header": build_response_header(body, request_name.replace("Request", "Response")),
                    "payload": {
                        props[0]: {
                            "value": prop["value"],
                            "scale": prop["scale"],
                        }
                    },
                }
            except KeyError:
                return error_response(body, "DriverInternalError")
            except ValueError:
                return error_response(body, "NotSupportedInCurrentModeError")
            except Exception:
                return error_response(body, "TargetConnectivityUnstableError")

        return error_response(body, "TargetConnectivityUnstableError")

    return router
