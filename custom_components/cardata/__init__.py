"""BMW CarData integration for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DEFAULT_SCOPE,
    DEFAULT_STREAM_HOST,
    DEFAULT_STREAM_PORT,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    MQTT_KEEPALIVE,
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    session = aiohttp.ClientSession()

    data = entry.data
    client_id = data["client_id"]
    gcid = data.get("gcid")
    id_token = data.get("id_token")
    if not gcid or not id_token:
        await session.close()
        raise ConfigEntryNotReady("Missing GCID or ID token")

    coordinator = CardataCoordinator(hass=hass, entry_id=entry.entry_id)

    manager = CardataStreamManager(
        hass=hass,
        client_id=client_id,
        gcid=gcid,
        id_token=id_token,
        host=data.get("mqtt_host", DEFAULT_STREAM_HOST),
        port=data.get("mqtt_port", DEFAULT_STREAM_PORT),
        keepalive=MQTT_KEEPALIVE,
    )
    manager.set_message_callback(coordinator.async_handle_message)

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
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data: CardataRuntimeData = hass.data[DOMAIN].pop(entry.entry_id)
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data.refresh_task.cancel()
    with suppress(asyncio.CancelledError):
        await data.refresh_task
    await data.stream.async_stop()
    await data.session.close()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


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

    token_data = await refresh_tokens(
        session,
        client_id=client_id,
        refresh_token=refresh_token,
        scope=DEFAULT_SCOPE,
    )

    data.update(
        {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token", refresh_token),
            "id_token": token_data.get("id_token"),
            "expires_in": token_data.get("expires_in"),
            "scope": token_data.get("scope", data.get("scope")),
            "token_type": token_data.get("token_type", data.get("token_type")),
            "received_at": time.time(),
        }
    )

    hass.config_entries.async_update_entry(entry, data=data)
    await manager.async_update_token(token_data.get("id_token"))
