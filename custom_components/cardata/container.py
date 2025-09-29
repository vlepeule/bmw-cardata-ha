"""Helpers for managing BMW CarData containers."""

from __future__ import annotations

import asyncio
import logging
import hashlib
from typing import Any, Dict, Iterable, Optional

import aiohttp

from .const import (
    API_BASE_URL,
    API_VERSION,
    DEBUG_LOG,
    HV_BATTERY_CONTAINER_NAME,
    HV_BATTERY_CONTAINER_PURPOSE,
    HV_BATTERY_DESCRIPTORS,
)

_LOGGER = logging.getLogger(__name__)


class CardataContainerError(Exception):
    """Raised when BMW CarData container management fails."""

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


class CardataContainerManager:
    """Ensure containers required for the integration exist."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        entry_id: str,
        initial_container_id: Optional[str] = None,
    ) -> None:
        self._session = session
        self._entry_id = entry_id
        self._container_id: Optional[str] = initial_container_id
        self._lock = asyncio.Lock()
        descriptors = list(dict.fromkeys(HV_BATTERY_DESCRIPTORS))
        self._desired_descriptors = tuple(descriptors)
        self._desired_descriptor_set = set(descriptors)
        self._descriptor_signature = self.compute_signature(descriptors)

    @property
    def container_id(self) -> Optional[str]:
        """Return the currently known container identifier."""

        return self._container_id

    @property
    def descriptor_signature(self) -> str:
        """Return the signature for the desired descriptor set."""

        return self._descriptor_signature

    @staticmethod
    def compute_signature(descriptors: Iterable[str]) -> str:
        """Return a stable signature for a descriptor collection."""

        normalized = sorted(dict.fromkeys(descriptors))
        joined = "|".join(normalized)
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()

    def sync_from_entry(self, container_id: Optional[str]) -> None:
        """Synchronize the known container id with stored config data."""

        if container_id:
            self._container_id = container_id

    async def async_ensure_hv_container(self, access_token: Optional[str]) -> Optional[str]:
        """Ensure the HV battery container exists and is active."""

        if not access_token:
            if DEBUG_LOG:
                _LOGGER.debug(
                    "[%s] Skipping container ensure because access token is missing",
                    self._entry_id,
                )
            return self._container_id

        async with self._lock:
            allow_reuse = True
            # Validate cached container id first.
            if self._container_id:
                details = await self._safe_get_container(access_token, self._container_id)
                if details and self._is_container_valid(details):
                    if DEBUG_LOG:
                        _LOGGER.debug(
                            "[%s] Using existing HV container %s",
                            self._entry_id,
                            self._container_id,
                        )
                    return self._container_id
                if details and self._is_ours(details):
                    await self._safe_delete_container(access_token, self._container_id)
                    allow_reuse = False
                self._container_id = None

            if allow_reuse:
                containers = await self._safe_list_containers(access_token)
                for container in containers:
                    container_id = container.get("containerId")
                    if not container_id:
                        continue
                    details = await self._safe_get_container(access_token, container_id)
                    if not details:
                        continue
                    if not self._matches_descriptors(details):
                        continue
                    if details.get("state") == "ACTIVE":
                        self._container_id = container_id
                        if DEBUG_LOG:
                            _LOGGER.debug(
                                "[%s] Reusing active HV container %s",
                                self._entry_id,
                                container_id,
                            )
                        return self._container_id
                    if self._is_ours(details):
                        await self._safe_delete_container(access_token, container_id)

            created_id = await self._create_container(access_token)
            self._container_id = created_id
            _LOGGER.info("[%s] Created HV battery container %s", self._entry_id, created_id)
            return self._container_id

    async def _safe_list_containers(self, access_token: str) -> Iterable[Dict[str, Any]]:
        try:
            payload = await self._request("GET", "/customers/containers", access_token)
        except CardataContainerError as err:
            raise CardataContainerError(f"Unable to list containers: {err}", status=err.status) from err
        containers = payload.get("containers") if isinstance(payload, dict) else None
        return containers or []

    async def _safe_get_container(
        self, access_token: str, container_id: str
    ) -> Optional[Dict[str, Any]]:
        try:
            return await self._request(
                "GET", f"/customers/containers/{container_id}", access_token
            )
        except CardataContainerError as err:
            if err.status == 404:
                if DEBUG_LOG:
                    _LOGGER.debug(
                        "[%s] Container %s no longer exists", self._entry_id, container_id
                    )
                return None
            raise CardataContainerError(
                f"Unable to read container {container_id}: {err}", status=err.status
            ) from err

    async def _safe_delete_container(self, access_token: str, container_id: str) -> None:
        try:
            await self._request(
                "DELETE", f"/customers/containers/{container_id}", access_token
            )
        except CardataContainerError as err:
            if err.status == 404:
                return
            raise CardataContainerError(
                f"Unable to delete container {container_id}: {err}", status=err.status
            ) from err
        if DEBUG_LOG:
            _LOGGER.debug(
                "[%s] Deleted inactive HV container %s", self._entry_id, container_id
            )

    async def _create_container(self, access_token: str) -> str:
        payload = {
            "name": HV_BATTERY_CONTAINER_NAME,
            "purpose": HV_BATTERY_CONTAINER_PURPOSE,
            "technicalDescriptors": list(self._desired_descriptors),
        }
        response = await self._request(
            "POST", "/customers/containers", access_token, json_body=payload
        )
        container_id = response.get("containerId") if isinstance(response, dict) else None
        if not container_id:
            raise CardataContainerError(
                "Container creation response missing containerId"
            )
        return container_id

    def _is_container_valid(self, details: Dict[str, Any]) -> bool:
        return (
            details.get("state") == "ACTIVE"
            and self._matches_descriptors(details)
        )

    def _matches_descriptors(self, details: Dict[str, Any]) -> bool:
        descriptors = details.get("technicalDescriptors")
        if not isinstance(descriptors, list):
            return False
        return set(descriptors) == self._desired_descriptor_set

    def _is_ours(self, details: Dict[str, Any]) -> bool:
        return (
            details.get("name") == HV_BATTERY_CONTAINER_NAME
            and details.get("purpose") == HV_BATTERY_CONTAINER_PURPOSE
        )

    async def _request(
        self,
        method: str,
        path: str,
        access_token: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-version": API_VERSION,
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        url = f"{API_BASE_URL}{path}"
        if DEBUG_LOG:
            _LOGGER.debug("[%s] %s %s", self._entry_id, method, url)
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status in (200, 201):
                    return await response.json(content_type=None)
                if response.status == 204:
                    return {}
                text = await response.text()
                raise CardataContainerError(
                    f"HTTP {response.status}: {text.strip() or 'no response body'}",
                    status=response.status,
                )
        except aiohttp.ClientError as err:
            raise CardataContainerError(f"Network error: {err}") from err
