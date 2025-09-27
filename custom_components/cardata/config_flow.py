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
from .const import DEFAULT_SCOPE, DOMAIN
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
                new_token = entry_data.get("id_token")
                if new_token:
                    self.hass.async_create_task(runtime.stream.async_update_token(new_token))
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
            try:
                await async_manual_refresh_tokens(self.hass, self._config_entry)
            except CardataAuthError as err:
                return self.async_show_form(
                    step_id="init",
                    data_schema=vol.Schema({}),
                    errors={"base": "refresh_failed"},
                    description_placeholders={"error": str(err)},
                )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
        )


async def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
    return CardataOptionsFlowHandler(config_entry)
