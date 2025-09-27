"""Handle BMW CarData MQTT streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import paho.mqtt.client as mqtt

from homeassistant.core import HomeAssistant

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

    async def async_start(self) -> None:
        await self.hass.async_add_executor_job(self._start_client)

    async def async_stop(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None

    async def async_update_token(self, id_token: Optional[str]) -> None:
        if not id_token:
            return
        self._password = id_token
        if self._client:
            _LOGGER.debug("Updating MQTT password; reconnecting")
            await self.async_stop()
            await self.async_start()

    def set_message_callback(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        self._message_callback = callback

    def _start_client(self) -> None:
        client = mqtt.Client(
            client_id=f"ha-cardata-{self._gcid}",
            clean_session=True,
            userdata={"topic": f"{self._gcid}/+/#", "reconnect": False},
        )
        client.username_pw_set(username=self._gcid, password=self._password)
        client.on_connect = self._handle_connect
        client.on_subscribe = self._handle_subscribe
        client.on_message = self._handle_message
        client.on_disconnect = self._handle_disconnect

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
                _LOGGER.debug("Subscribed to %s result=%s", topic, result)
        else:
            _LOGGER.error("BMW MQTT connection failed: rc=%s", rc)

    def _handle_subscribe(self, client: mqtt.Client, userdata, mid, granted_qos) -> None:
        _LOGGER.debug("BMW MQTT subscribed mid=%s qos=%s", mid, granted_qos)

    def _handle_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
        payload = msg.payload.decode(errors="ignore")
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
        _LOGGER.warning("BMW MQTT disconnected rc=%s", rc)
        if userdata is not None and isinstance(userdata, dict):
            userdata["reconnect"] = True
        asyncio.run_coroutine_threadsafe(self._async_reconnect(), self.hass.loop)

    async def _async_reconnect(self) -> None:
        await self.async_stop()
        await asyncio.sleep(5)
        try:
            await self.async_start()
        except Exception as err:
            _LOGGER.error("BMW MQTT reconnect failed: %s", err)
