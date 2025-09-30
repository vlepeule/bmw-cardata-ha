"""Config flow for BMW CarData integration."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import string
import time
from typing import Any, Dict, Optional

import aiohttp
import voluptuous as vol

import logging

from homeassistant import config_entries
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from . import async_manual_refresh_tokens
from .const import (
    DEFAULT_SCOPE,
    DOMAIN,
    OPTION_MQTT_KEEPALIVE,
    OPTION_DIAGNOSTIC_INTERVAL,
    OPTION_DEBUG_LOG,
    VEHICLE_METADATA,
)
from .device_flow import CardataAuthError, poll_for_tokens, request_device_code

DATA_SCHEMA = vol.Schema({vol.Required("client_id"): str})


def _build_code_verifier() -> str:
    alphabet = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(alphabet) for _ in range(86))


def _generate_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class CardataConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for BMW CarData."""

    VERSION = 1

    def __init__(self) -> None:
        self._client_id: Optional[str] = None
        self._device_data: Optional[Dict[str, Any]] = None
        self._code_verifier: Optional[str] = None
        self._token_data: Optional[Dict[str, Any]] = None
        self._reauth_entry: Optional[ConfigEntry] = None

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        client_id = user_input["client_id"].strip()

        for entry in list(self._async_current_entries()):
            existing_client_id = entry.data.get("client_id") if hasattr(entry, "data") else None
            if entry.unique_id == client_id or existing_client_id == client_id:
                await self.hass.config_entries.async_remove(entry.entry_id)

        await self.async_set_unique_id(client_id)

        self._client_id = client_id

        try:
            await self._request_device_code()
        except CardataAuthError as err:
            return self.async_show_form(
                step_id="user",
                data_schema=DATA_SCHEMA,
                errors={"base": "device_code_failed"},
                description_placeholders={"error": str(err)},
            )

        return await self.async_step_authorize()

    async def _request_device_code(self) -> None:
        assert self._client_id is not None
        self._code_verifier = _build_code_verifier()
        async with aiohttp.ClientSession() as session:
            self._device_data = await request_device_code(
                session,
                client_id=self._client_id,
                scope=DEFAULT_SCOPE,
                code_challenge=_generate_code_challenge(self._code_verifier),
            )

    async def async_step_authorize(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        assert self._client_id is not None
        assert self._device_data is not None
        assert self._code_verifier is not None

        placeholders = {
            "verification_url": self._device_data.get("verification_uri_complete")
            or self._device_data.get("verification_uri"),
            "user_code": self._device_data.get("user_code", ""),
        }

        if user_input is None:
            return self.async_show_form(
                step_id="authorize",
                data_schema=vol.Schema({vol.Required("confirmed", default=True): bool}),
                description_placeholders=placeholders,
            )

        device_code = self._device_data["device_code"]
        interval = int(self._device_data.get("interval", 5))

        async with aiohttp.ClientSession() as session:
            try:
                token_data = await poll_for_tokens(
                    session,
                    client_id=self._client_id,
                    device_code=device_code,
                    code_verifier=self._code_verifier,
                    interval=interval,
                    timeout=int(self._device_data.get("expires_in", 600)),
                )
            except CardataAuthError as err:
                LOGGER.warning("BMW authorization pending/failed: %s", err)
                return self.async_show_form(
                    step_id="authorize",
                    data_schema=vol.Schema({vol.Required("confirmed", default=True): bool}),
                    errors={"base": "authorization_failed"},
                    description_placeholders={"error": str(err), **placeholders},
                )

        self._token_data = token_data
        LOGGER.debug("Received token: scope=%s id_token_length=%s", token_data.get("scope"), len(token_data.get("id_token") or ""))
        return await self.async_step_tokens()

    async def async_step_tokens(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        assert self._client_id is not None
        token_data = self._token_data

        entry_data = {
            "client_id": self._client_id,
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "id_token": token_data.get("id_token"),
            "expires_in": token_data.get("expires_in"),
            "scope": token_data.get("scope"),
            "gcid": token_data.get("gcid"),
            "token_type": token_data.get("token_type"),
            "received_at": time.time(),
        }

        if self._reauth_entry:
            self.hass.config_entries.async_update_entry(self._reauth_entry, data=entry_data)
            runtime = self.hass.data.get(DOMAIN, {}).get(self._reauth_entry.entry_id)
            if runtime:
                runtime.reauth_in_progress = False
                runtime.reauth_flow_id = None
                runtime.last_reauth_attempt = 0.0
                runtime.last_refresh_attempt = 0.0
                new_token = entry_data.get("id_token")
                new_gcid = entry_data.get("gcid")
                if new_token or new_gcid:
                    self.hass.async_create_task(
                        runtime.stream.async_update_credentials(
                            gcid=new_gcid,
                            id_token=new_token,
                        )
                    )
            notification_id = f"{DOMAIN}_reauth_{self._reauth_entry.entry_id}"
            persistent_notification.async_dismiss(self.hass, notification_id)
            return self.async_abort(reason="reauth_successful")

        friendly_title = f"BimmerData Streamline ({self._client_id[:8]})"
        return self.async_create_entry(title=friendly_title, data=entry_data)

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> FlowResult:
        entry_id = entry_data.get("entry_id")
        if entry_id:
            self._reauth_entry = self.hass.config_entries.async_get_entry(entry_id)
        self._client_id = entry_data.get("client_id")
        await self._request_device_code()
        return await self.async_step_authorize()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return CardataOptionsFlowHandler(config_entry)

LOGGER = logging.getLogger(__name__)


class CardataOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is not None:
            overrides, errors = self._parse_overrides(user_input)
            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._build_schema(),
                    errors=errors,
                )

            overrides_changed = self._apply_overrides(overrides)

            action = user_input.get("action", "apply_overrides")
            if action == "reauth":
                if overrides_changed:
                    self.hass.config_entries.async_schedule_reload(self._config_entry.entry_id)
                return await self._handle_reauth()

            if action == "refresh_tokens":
                result = await self._handle_refresh_tokens()
            elif action == "fetch_mappings":
                result = await self._handle_fetch_mappings()
            elif action == "fetch_basic_data":
                result = await self._handle_fetch_basic_data()
            elif action == "fetch_telematic":
                result = await self._handle_fetch_telematic()
            else:
                result = self.async_create_entry(title="", data={})

            if overrides_changed:
                self.hass.config_entries.async_schedule_reload(self._config_entry.entry_id)

            return result

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(),
        )

    def _build_schema(self) -> vol.Schema:
        options = self._config_entry.options or {}
        keepalive_default = str(options.get(OPTION_MQTT_KEEPALIVE, ""))
        diagnostic_default = str(options.get(OPTION_DIAGNOSTIC_INTERVAL, ""))
        debug_default = options.get(OPTION_DEBUG_LOG)
        if debug_default is True:
            debug_choice = "true"
        elif debug_default is False:
            debug_choice = "false"
        else:
            debug_choice = "default"
        return vol.Schema(
            {
                vol.Required(
                    "action",
                    default="apply_overrides",
                ): vol.In(
                    {
                        "apply_overrides": "Save overrides only",
                        "refresh_tokens": "Refresh tokens",
                        "reauth": "Start device authorization again",
                        "fetch_mappings": "Initiate vehicles (API)",
                        "fetch_basic_data": "Get basic vehicle information (API)",
                        "fetch_telematic": "Get telematics data (API)",
                    }
                ),
                vol.Optional(
                    "mqtt_keepalive",
                    default=keepalive_default,
                ): str,
                vol.Optional(
                    "diagnostic_log_interval",
                    default=diagnostic_default,
                ): str,
                vol.Optional(
                    "debug_log",
                    default=debug_choice,
                ): vol.In({"default": "Use default", "true": "Enabled", "false": "Disabled"}),
            }
        )

    def _parse_overrides(self, user_input: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        overrides: Dict[str, Any] = {}
        errors: Dict[str, str] = {}

        keepalive_raw = user_input.get("mqtt_keepalive")
        if keepalive_raw is not None:
            keepalive_raw = keepalive_raw.strip()
            if keepalive_raw:
                try:
                    value = int(keepalive_raw)
                    if value <= 0:
                        raise ValueError
                except ValueError:
                    errors["mqtt_keepalive"] = "invalid_int"
                else:
                    overrides[OPTION_MQTT_KEEPALIVE] = value
            else:
                overrides[OPTION_MQTT_KEEPALIVE] = None

        diagnostic_raw = user_input.get("diagnostic_log_interval")
        if diagnostic_raw is not None:
            diagnostic_raw = diagnostic_raw.strip()
            if diagnostic_raw:
                try:
                    value = int(diagnostic_raw)
                    if value <= 0:
                        raise ValueError
                except ValueError:
                    errors["diagnostic_log_interval"] = "invalid_int"
                else:
                    overrides[OPTION_DIAGNOSTIC_INTERVAL] = value
            else:
                overrides[OPTION_DIAGNOSTIC_INTERVAL] = None

        debug_choice = user_input.get("debug_log")
        if debug_choice == "true":
            overrides[OPTION_DEBUG_LOG] = True
        elif debug_choice == "false":
            overrides[OPTION_DEBUG_LOG] = False
        else:
            overrides[OPTION_DEBUG_LOG] = None

        return overrides, errors

    def _apply_overrides(self, overrides: Dict[str, Any]) -> bool:
        options = dict(self._config_entry.options)
        changed = False
        for key, value in overrides.items():
            if value is None:
                if key in options:
                    options.pop(key)
                    changed = True
            else:
                if options.get(key) != value:
                    options[key] = value
                    changed = True
        if changed:
            self.hass.config_entries.async_update_entry(self._config_entry, options=options)
        return changed

    async def _handle_refresh_tokens(self) -> FlowResult:
        try:
            await async_manual_refresh_tokens(self.hass, self._config_entry)
        except CardataAuthError as err:
            return self.async_show_form(
                step_id="init",
                data_schema=self._build_schema(),
                errors={"base": "refresh_failed"},
                description_placeholders={"error": str(err)},
            )
        return self.async_create_entry(title="", data={})

    async def _handle_reauth(self) -> FlowResult:
        entry = self._config_entry
        if entry is None:
            return self.async_abort(reason="unknown")

        cleared = dict(entry.data)
        for key in (
            "access_token",
            "refresh_token",
            "id_token",
            "expires_in",
            "scope",
            "gcid",
            "token_type",
            "received_at",
        ):
            cleared.pop(key, None)

        self.hass.config_entries.async_update_entry(entry, data=cleared)

        await self.hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH},
            data={"client_id": entry.data.get("client_id"), "entry_id": entry.entry_id},
        )
        await self.hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH},
            data={"client_id": entry.data.get("client_id"), "entry_id": entry.entry_id},
        )
        return self.async_abort(reason="reauth_started")

    async def _handle_fetch_mappings(self) -> FlowResult:
        runtime = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        if runtime is None:
            return self.async_show_form(
                step_id="init",
                data_schema=self._build_schema(),
                errors={"base": "runtime_missing"},
            )
        await self.hass.services.async_call(
            DOMAIN,
            "fetch_vehicle_mappings",
            {"entry_id": self._config_entry.entry_id},
            blocking=True,
        )
        return self.async_create_entry(title="", data={})

    async def _handle_fetch_telematic(self) -> FlowResult:
        runtime = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        if runtime is None:
            return self.async_show_form(
                step_id="init",
                data_schema=self._build_schema(),
                errors={"base": "runtime_missing"},
            )
        await self.hass.services.async_call(
            DOMAIN,
            "fetch_telematic_data",
            {"entry_id": self._config_entry.entry_id},
            blocking=True,
        )
        return self.async_create_entry(title="", data={})

    async def _handle_fetch_basic_data(self) -> FlowResult:
        runtime = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        if runtime is None:
            return self.async_show_form(
                step_id="init",
                data_schema=self._build_schema(),
                errors={"base": "runtime_missing"},
            )

        vins = set()
        vins.update(runtime.coordinator.data.keys())
        metadata = self._config_entry.data.get(VEHICLE_METADATA)
        if isinstance(metadata, dict):
            vins.update(metadata.keys())
        if (entry_vin := self._config_entry.data.get("vin")):
            vins.add(entry_vin)
        if not vins:
            return self.async_show_form(
                step_id="init",
                data_schema=self._build_schema(),
                errors={"base": "no_vins"},
            )

        for vin in sorted(v for v in vins if isinstance(v, str)):
            await self.hass.services.async_call(
                DOMAIN,
                "fetch_basic_data",
                {"entry_id": self._config_entry.entry_id, "vin": vin},
                blocking=True,
            )

        return self.async_create_entry(title="", data={})


async def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
    return CardataOptionsFlowHandler(config_entry)
