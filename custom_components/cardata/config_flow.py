"""Config flow for BMW CarData integration."""

from __future__ import annotations

import asyncio
import secrets
import string
import time
from typing import Any, Dict, Optional

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DEFAULT_SCOPE, DOMAIN
from .device_flow import CardataAuthError, poll_for_tokens, request_device_code

DATA_SCHEMA = vol.Schema({vol.Required("client_id"): str})


def _build_code_verifier() -> str:
    alphabet = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(alphabet) for _ in range(86))


class CardataConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for BMW CarData."""

    VERSION = 1

    def __init__(self) -> None:
        self._client_id: Optional[str] = None
        self._device_data: Optional[Dict[str, Any]] = None
        self._code_verifier: Optional[str] = None
        self._token_data: Optional[Dict[str, Any]] = None

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        client_id = user_input["client_id"].strip()
        await self.async_set_unique_id(client_id)
        self._abort_if_unique_id_configured()

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
                description=(
                    "Open {verification_url} and enter the user code {user_code}. "
                    "Once you've approved the device, press Submit to continue."
                ),
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
                return self.async_show_form(
                    step_id="authorize",
                    data_schema=vol.Schema({vol.Required("confirmed", default=True): bool}),
                    errors={"base": "authorization_failed"},
                    description=(
                        "Open {verification_url} and enter the user code {user_code}. "
                        "Once you've approved the device, press Submit to continue.\n"
                        "Error: {error}"
                    ),
                    description_placeholders={"error": str(err), **placeholders},
                )

        self._token_data = token_data
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

        return self.async_create_entry(title=self._client_id, data=entry_data)

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> FlowResult:
        self._client_id = entry_data.get("client_id")
        await self._request_device_code()
        return await self.async_step_authorize()
