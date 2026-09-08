"""Lock platform entity for Virtual HomeKit Lock."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_FINISH_COLOR,
    CONF_NAME,
    CONF_PORT,
    CONF_SETUP_CODE,
    CONF_SETUP_ID,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    URL_DOWNLOAD_HOMEKEYC,
)
from .homekit_lock import HomeKeyLockAccessory
from .storage import HomeKeyStore

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HomeKey Lock entity from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    store: HomeKeyStore = data["store"]
    accessory: HomeKeyLockAccessory = data["accessory"]
    setup_payload: str = data.get("setup_payload", "")

    entity = HomeKeyLockEntity(
        entry=entry,
        store=store,
        accessory=accessory,
        setup_payload=setup_payload,
    )
    async_add_entities([entity])


class HomeKeyLockEntity(LockEntity):
    """Representation of the Virtual HomeKit Lock with HomeKey extraction capabilities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        store: HomeKeyStore,
        accessory: HomeKeyLockAccessory,
        setup_payload: str,
    ) -> None:
        """Initialize lock entity."""
        self.entry = entry
        self.store = store
        self.accessory = accessory
        self.setup_payload = setup_payload
        
        self._attr_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
        self._attr_unique_id = f"{entry.entry_id}_virtual_lock"
        self._attr_is_locked = True

        # Register callback for bi-directional state sync from HomeKit
        self.accessory.lock_state_callback = self._on_homekit_state_change

    def _on_homekit_state_change(self, value: int) -> None:
        """Handle state updates initiated from Apple HomeKit."""
        _LOGGER.info("Updating Home Assistant lock entity state from HomeKit: value=%d", value)
        self._attr_is_locked = (value == 1)
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self._attr_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version="2.0.0",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes for HomeKey token status and pairing info."""
        sk_provisioned = self.store.sk_r is not None

        try:
            from homeassistant.helpers.network import get_url
            base_url = get_url(self.hass, prefer_external=False)
        except Exception:
            base_url = ""

        local_www_url = f"{base_url}/local/homekeyc.h" if base_url else "/local/homekeyc.h"
        api_download_url = f"{base_url}{URL_DOWNLOAD_HOMEKEYC}" if base_url else URL_DOWNLOAD_HOMEKEYC
        
        attrs: dict[str, Any] = {
            "setup_code": self.entry.data.get(CONF_SETUP_CODE),
            "setup_id": self.entry.data.get(CONF_SETUP_ID),
            "hap_port": self.entry.data.get(CONF_PORT),
            "setup_payload": self.setup_payload,
            "finish_color": self.entry.data.get(CONF_FINISH_COLOR),
            "reader_key_provisioned": sk_provisioned,
            "group_id": self.store.gid.hex() if self.store.gid else None,
            "sub_id": self.store.sub_id.hex() if self.store.sub_id else None,
            "endpoint_count": len(self.store.endpoints),
            "configuration_state": self.store.configuration_state,
            "header_file_path": "/config/homekeyc.h",
            "direct_download_url": local_www_url,
            "api_download_url": api_download_url,
            "download_instructions": f"Find homekeyc.h in your HA /config/ folder or download at {local_www_url}",
        }
        return attrs

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the virtual lock."""
        _LOGGER.info("Locking virtual HomeKit lock")
        self.accessory.set_lock_target(1)
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the virtual lock."""
        _LOGGER.info("Unlocking virtual HomeKit lock")
        self.accessory.set_lock_target(0)
        self._attr_is_locked = False
        self.async_write_ha_state()
