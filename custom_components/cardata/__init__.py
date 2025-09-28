"""BMW CarData integration for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict

import aiohttp

from homeassistant.config_entries import ConfigEntry, SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from homeassistant.components import persistent_notification

from .const import (
    DEFAULT_SCOPE,
    DEFAULT_STREAM_HOST,
    DEFAULT_STREAM_PORT,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    MQTT_KEEPALIVE,
    DIAGNOSTIC_LOG_INTERVAL,
)
from .device_flow import CardataAuthError, refresh_tokens
from .stream import CardataStreamManager
from .coordinator import CardataCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "binary_sensor"]

@dataclass
class CardataRuntimeData:
    stream: CardataStreamManager
    refresh_task: asyncio.Task
    session: aiohttp.ClientSession
    coordinator: CardataCoordinator
    reauth_in_progress: bool = False
    reauth_flow_id: str | None = None
    last_reauth_attempt: float = 0.0
    last_refresh_attempt: float = 0.0
    reauth_pending: bool = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    _LOGGER.debug("Setting up BimmerData Streamline entry %s", entry.entry_id)

    session = aiohttp.ClientSession()

    data = entry.data
    client_id = data["client_id"]
    gcid = data.get("gcid")
    id_token = data.get("id_token")
    if not gcid or not id_token:
        await session.close()
        raise ConfigEntryNotReady("Missing GCID or ID token")

    coordinator = CardataCoordinator(hass=hass, entry_id=entry.entry_id)

    async def handle_stream_error(reason: str) -> None:
        await _handle_stream_error(hass, entry, reason)

    manager = CardataStreamManager(
        hass=hass,
        client_id=client_id,
        gcid=gcid,
        id_token=id_token,
        host=data.get("mqtt_host", DEFAULT_STREAM_HOST),
        port=data.get("mqtt_port", DEFAULT_STREAM_PORT),
        keepalive=MQTT_KEEPALIVE,
        error_callback=handle_stream_error,
    )
    manager.set_message_callback(coordinator.async_handle_message)
    manager.set_status_callback(coordinator.async_handle_connection_event)

    try:
        await manager.async_start()
    except Exception as err:
        await session.close()
        raise ConfigEntryNotReady(f"Unable to connect to BMW MQTT: {err}") from err

    refresh_task = hass.loop.create_task(_refresh_loop(hass, entry, session, manager))

    hass.data[DOMAIN][entry.entry_id] = CardataRuntimeData(
        stream=manager,
        refresh_task=refresh_task,
        session=session,
        coordinator=coordinator,
        reauth_in_progress=False,
        reauth_flow_id=None,
    )

    await coordinator.async_handle_connection_event("connecting")
    await coordinator.async_start_watchdog()

    hass.async_create_task(_async_refresh_on_startup(hass, entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.get(DOMAIN)
    if not domain_data or entry.entry_id not in domain_data:
        return True
    data: CardataRuntimeData = domain_data.pop(entry.entry_id)
    await data.coordinator.async_stop_watchdog()
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data.refresh_task.cancel()
    with suppress(asyncio.CancelledError):
        await data.refresh_task
    await data.stream.async_stop()
    await data.session.close()
    if not domain_data:
        hass.data.pop(DOMAIN)
    return True


async def _handle_stream_error(hass: HomeAssistant, entry: ConfigEntry, reason: str) -> None:
    runtime: CardataRuntimeData = hass.data[DOMAIN][entry.entry_id]
    notification_id = f"{DOMAIN}_reauth_{entry.entry_id}"
    if reason == "unauthorized":
        if runtime.reauth_in_progress:
            _LOGGER.debug("Ignoring duplicate unauthorized notification for entry %s", entry.entry_id)
            return

        now = time.time()

        if runtime.reauth_pending:
            _LOGGER.debug(
                "Reauth pending for entry %s after failed refresh; starting flow",
                entry.entry_id,
            )
        elif now - runtime.last_refresh_attempt >= DIAGNOSTIC_LOG_INTERVAL:
            runtime.last_refresh_attempt = now
            try:
                _LOGGER.info(
                    "Attempting token refresh after unauthorized response for entry %s",
                    entry.entry_id,
                )
                await _refresh_tokens(entry, runtime.session, runtime.stream)
                runtime.reauth_in_progress = False
                runtime.last_reauth_attempt = 0.0
                runtime.reauth_pending = False
                return
            except CardataAuthError as err:
                _LOGGER.warning(
                    "Token refresh after unauthorized failed for entry %s: %s",
                    entry.entry_id,
                    err,
                )
        else:
            runtime.reauth_pending = True
            _LOGGER.debug(
                "Token refresh attempted recently for entry %s; will trigger reauth",
                entry.entry_id,
            )

        if now - runtime.last_reauth_attempt < DIAGNOSTIC_LOG_INTERVAL:
            _LOGGER.debug(
                "Recent reauth already attempted for entry %s; skipping new flow",
                entry.entry_id,
            )
            return

        runtime.reauth_in_progress = True
        runtime.last_reauth_attempt = now
        runtime.reauth_pending = False
        _LOGGER.error("BMW stream unauthorized; starting reauth flow")
        if runtime.reauth_flow_id:
            with suppress(Exception):
                await hass.config_entries.flow.async_abort(runtime.reauth_flow_id)
            runtime.reauth_flow_id = None
        persistent_notification.async_create(
            hass,
            "Authorization failed for BMW CarData. Please reauthorize the integration.",
            title="BimmerData Streamline",
            notification_id=notification_id,
        )
        flow_result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data={**entry.data, "entry_id": entry.entry_id},
        )
        if isinstance(flow_result, dict):
            runtime.reauth_flow_id = flow_result.get("flow_id")
    elif reason == "recovered":
        if runtime.reauth_in_progress:
            runtime.reauth_in_progress = False
            _LOGGER.info("BMW stream connection restored; dismissing reauth notification")
            persistent_notification.async_dismiss(hass, notification_id)
            if runtime.reauth_flow_id:
                with suppress(Exception):
                    await hass.config_entries.flow.async_abort(runtime.reauth_flow_id)
                runtime.reauth_flow_id = None
        runtime.reauth_pending = False
        runtime.last_reauth_attempt = 0.0


async def _refresh_loop(
    hass: HomeAssistant,
    entry: ConfigEntry,
    session: aiohttp.ClientSession,
    manager: CardataStreamManager,
) -> None:
    try:
        while True:
            await asyncio.sleep(DEFAULT_REFRESH_INTERVAL)
            try:
                await _refresh_tokens(entry, session, manager)
            except CardataAuthError as err:
                _LOGGER.error("Token refresh failed: %s", err)
    except asyncio.CancelledError:
        return


async def _refresh_tokens(
    entry: ConfigEntry,
    session: aiohttp.ClientSession,
    manager: CardataStreamManager,
) -> None:
    hass = manager.hass
    data = dict(entry.data)
    refresh_token = data.get("refresh_token")
    client_id = data.get("client_id")
    if not refresh_token or not client_id:
        raise CardataAuthError("Missing credentials for refresh")

    requested_scope = data.get("scope") or DEFAULT_SCOPE

    token_data = await refresh_tokens(
        session,
        client_id=client_id,
        refresh_token=refresh_token,
        scope=requested_scope,
    )

    new_id_token = token_data.get("id_token")
    if not new_id_token:
        raise CardataAuthError("Token refresh response did not include id_token")
    data.update(
        {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token", refresh_token),
            "id_token": new_id_token,
            "expires_in": token_data.get("expires_in"),
            "scope": token_data.get("scope", data.get("scope")),
            "token_type": token_data.get("token_type", data.get("token_type")),
            "received_at": time.time(),
        }
    )

    hass.config_entries.async_update_entry(entry, data=data)
    await manager.async_update_token(new_id_token)
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime:
        runtime.reauth_pending = False


async def async_manual_refresh_tokens(hass: HomeAssistant, entry: ConfigEntry) -> None:
    runtime: CardataRuntimeData | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is None:
        raise CardataAuthError("Integration runtime not ready")
    await _refresh_tokens(entry, runtime.session, runtime.stream)


async def _async_refresh_on_startup(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.async_block_till_done()
    runtime: CardataRuntimeData | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is None:
        return
    try:
        await _refresh_tokens(entry, runtime.session, runtime.stream)
    except CardataAuthError as err:
        _LOGGER.warning("Initial token refresh failed: %s", err)
