"""Handle BMW CarData MQTT streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Awaitable, Callable, Optional

import paho.mqtt.client as mqtt

from homeassistant.core import HomeAssistant

from .const import DEBUG_LOG, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CardataStreamManager:
    """Manage the MQTT connection to BMW CarData."""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        client_id: str,
        gcid: str,
        id_token: str,
        host: str,
        port: int,
        keepalive: int,
        error_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        self.hass = hass
        self._client_id = client_id
        self._gcid = gcid
        self._password = id_token
        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._client: Optional[mqtt.Client] = None
        self._message_callback: Optional[Callable[[dict], Awaitable[None]]] = None
        self._error_callback = error_callback
        self._reauth_notified = False
        self._unauthorized_retry_in_progress = False
        self._awaiting_new_credentials = False
        self._status_callback: Optional[
            Callable[[str, Optional[str]], Awaitable[None]]
        ] = None
        self._reconnect_backoff = 5
        self._max_backoff = 300

    async def async_start(self) -> None:
        await self.hass.async_add_executor_job(self._start_client)
        self._reconnect_backoff = 5

    async def async_stop(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None

    @property
    def client(self) -> Optional[mqtt.Client]:
        return self._client

    def set_message_callback(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        self._message_callback = callback

    def set_status_callback(
        self, callback: Callable[[str, Optional[str]], Awaitable[None]]
    ) -> None:
        self._status_callback = callback

    def _start_client(self) -> None:
        client_id = self._gcid
        client = mqtt.Client(
            client_id=client_id,
            clean_session=True,
            userdata={"topic": f"{self._gcid}/+", "reconnect": False},
            protocol=mqtt.MQTTv311,
            transport="tcp",
        )
        if DEBUG_LOG:
            _LOGGER.debug(
                "Initializing MQTT client: client_id=%s host=%s port=%s",
                client_id,
                self._host,
                self._port,
            )
        client.username_pw_set(username=self._gcid, password=self._password)
        if DEBUG_LOG:
            _LOGGER.debug(
                "MQTT credentials set for GCID %s (token length=%s)",
                self._gcid,
                len(self._password or ""),
            )
        client.on_connect = self._handle_connect
        client.on_subscribe = self._handle_subscribe
        client.on_message = self._handle_message
        client.on_disconnect = self._handle_disconnect
        context = ssl.create_default_context()
        if hasattr(ssl, "TLSVersion"):
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            if hasattr(context, "maximum_version"):
                context.maximum_version = ssl.TLSVersion.TLSv1_2
        client.tls_set_context(context)
        client.tls_insecure_set(False)
        client.reconnect_delay_set(min_delay=5, max_delay=60)

        try:
            client.connect(self._host, self._port, keepalive=self._keepalive)
        except Exception as err:
            _LOGGER.error("Unable to connect to BMW MQTT: %s", err)
            client.loop_stop()
            raise
        client.loop_start()
        self._client = client

    def _handle_connect(self, client: mqtt.Client, userdata, flags, rc) -> None:
        if rc == 0:
            topic = userdata.get("topic")
            if topic:
                result = client.subscribe(topic)
                if DEBUG_LOG:
                    _LOGGER.debug("Subscribed to %s result=%s", topic, result)
            if self._reauth_notified:
                self._reauth_notified = False
                self._awaiting_new_credentials = False
                asyncio.run_coroutine_threadsafe(self._notify_recovered(), self.hass.loop)
            if self._status_callback:
                asyncio.run_coroutine_threadsafe(
                    self._status_callback("connected"),
                    self.hass.loop,
                )
        elif rc in (4, 5):  # bad credentials / not authorized
            _LOGGER.error("BMW MQTT connection failed: rc=%s", rc)
            asyncio.run_coroutine_threadsafe(self._handle_unauthorized(), self.hass.loop)
            client.loop_stop()
            self._client = None
            return
        elif self._status_callback:
            asyncio.run_coroutine_threadsafe(
                self._status_callback("connection_failed", reason=str(rc)),
                self.hass.loop,
            )

    def _handle_subscribe(self, client: mqtt.Client, userdata, mid, granted_qos) -> None:
        if DEBUG_LOG:
            _LOGGER.debug("BMW MQTT subscribed mid=%s qos=%s", mid, granted_qos)

    def _handle_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
        payload = msg.payload.decode(errors="ignore")
        if DEBUG_LOG:
            _LOGGER.debug("BMW MQTT message on %s: %s", msg.topic, payload)
        if not self._message_callback:
            return
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        if self._message_callback:
            asyncio.run_coroutine_threadsafe(self._message_callback(data), self.hass.loop)

    def _handle_disconnect(self, client: mqtt.Client, userdata, rc) -> None:
        reason = {
            1: "Unacceptable protocol version",
            2: "Identifier rejected",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized",
        }.get(rc, "Unknown")
        _LOGGER.warning("BMW MQTT disconnected rc=%s (%s)", rc, reason)
        if userdata is not None and isinstance(userdata, dict):
            userdata["reconnect"] = True
        if rc in (4, 5):
            asyncio.run_coroutine_threadsafe(self._handle_unauthorized(), self.hass.loop)
            self._reconnect_backoff = min(self._reconnect_backoff * 2, self._max_backoff)
            if self._status_callback:
                asyncio.run_coroutine_threadsafe(
                    self._status_callback("unauthorized", reason=reason),
                    self.hass.loop,
                )
        else:
            asyncio.run_coroutine_threadsafe(self._async_reconnect(), self.hass.loop)
            if self._status_callback:
                asyncio.run_coroutine_threadsafe(
                    self._status_callback("disconnected", reason=reason),
                    self.hass.loop,
                )

    async def _async_reconnect(self) -> None:
        await self.async_stop()
        await asyncio.sleep(self._reconnect_backoff)
        try:
            await self.async_start()
        except Exception as err:
            _LOGGER.error("BMW MQTT reconnect failed: %s", err)
            self._reconnect_backoff = min(self._reconnect_backoff * 2, self._max_backoff)
        else:
            self._reconnect_backoff = 5

    async def _handle_unauthorized(self) -> None:
        if self._unauthorized_retry_in_progress:
            return
        self._unauthorized_retry_in_progress = True
        try:
            self._awaiting_new_credentials = True
            if not self._reauth_notified:
                self._reauth_notified = True
                await self._notify_error("unauthorized")
            else:
                await self.async_stop()
            if self._status_callback:
                await self._status_callback("unauthorized", reason="MQTT rc=5")
        finally:
            self._unauthorized_retry_in_progress = False

    async def _notify_error(self, reason: str) -> None:
        await self.async_stop()
        if self._error_callback:
            await self._error_callback(reason)

    async def _notify_recovered(self) -> None:
        if self._error_callback:
            await self._error_callback("recovered")

    async def async_update_credentials(
        self,
        *,
        gcid: Optional[str] = None,
        id_token: Optional[str] = None,
    ) -> None:
        if not gcid and not id_token:
            return

        reconnect_required = False

        if gcid and gcid != self._gcid:
            _LOGGER.debug("Updating MQTT GCID from %s to %s", self._gcid, gcid)
            self._gcid = gcid
            reconnect_required = True

        if id_token and id_token != self._password:
            self._password = id_token
            reconnect_required = True

        if not reconnect_required:
            if self._awaiting_new_credentials:
                self._awaiting_new_credentials = False
            return

        if self._client:
            _LOGGER.debug("Updating MQTT credentials; reconnecting")
            await self.async_stop()

        self._reconnect_backoff = 5
        if self._awaiting_new_credentials:
            self._awaiting_new_credentials = False

        try:
            await self.async_start()
        except Exception as err:
            _LOGGER.error("BMW MQTT reconnect failed after credential update: %s", err)

    async def async_update_token(self, id_token: Optional[str]) -> None:
        await self.async_update_credentials(id_token=id_token)
