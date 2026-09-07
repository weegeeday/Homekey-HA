"""Apple HomeKey Token Extractor integration for Home Assistant."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import persistent_notification
from pyhap.accessory_driver import AccessoryDriver

from .const import (
    CATEGORY_DOOR_LOCK,
    CONF_FINISH_COLOR,
    CONF_NAME,
    CONF_PORT,
    CONF_SETUP_CODE,
    CONF_SETUP_ID,
    DEFAULT_FINISH_COLOR,
    DEFAULT_NAME,
    DOMAIN,
    URL_DOWNLOAD_HOMEKEYC,
)
from .homekit_lock import HomeKeyLockAccessory
from .http import HomeKeyHeaderView
from .storage import HomeKeyStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["lock"]


def get_setup_payload(setup_code: str, setup_id: str) -> str:
    """Generate official HomeKit setup payload URI (X-HM://...)."""
    try:
        from pyhap.qr import QR
        qr_obj = QR(setup_code=setup_code, setup_id=setup_id, category=CATEGORY_DOOR_LOCK)
        return qr_obj.payload
    except Exception as err:
        _LOGGER.debug("PyHAP QR payload generation fallback: %s", err)
        return f"X-HM://SETUPCODE={setup_code}&SETUPID={setup_id}"


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Apple HomeKey integration from a config entry."""
    entry_id = entry.entry_id
    hass.data.setdefault(DOMAIN, {})

    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    port = entry.data.get(CONF_PORT, 51827)
    setup_code = entry.data.get(CONF_SETUP_CODE, "111-22-333")
    setup_id = entry.data.get(CONF_SETUP_ID, "HK12")
    finish_color = entry.data.get(CONF_FINISH_COLOR, DEFAULT_FINISH_COLOR)

    # Initialize key store
    store = HomeKeyStore(hass, entry_id)
    await store.async_load()

    # Register HTTP View (only once if not already registered)
    if "http_view_registered" not in hass.data[DOMAIN]:
        view = HomeKeyHeaderView(store)
        hass.http.register_view(view)
        hass.data[DOMAIN]["http_view_registered"] = True

    # Configure PyHAP Driver
    state_file = hass.config.path(f".apple_homekey_{entry_id}.state")
    
    driver = AccessoryDriver(
        port=port,
        address="",
        state_file=state_file,
        loop=hass.loop,
    )

    # Set driver setup credentials
    driver.state.setup_code = setup_code.encode("ascii")
    if hasattr(driver.state, "setup_id"):
        driver.state.setup_id = setup_id

    # Create virtual HomeKit lock accessory
    accessory = HomeKeyLockAccessory(
        driver=driver,
        name=name,
        store=store,
        finish_color=finish_color,
        hass=hass,
    )
    driver.add_accessory(accessory)

    # Generate HomeKit setup QR payload string
    setup_payload = get_setup_payload(setup_code, setup_id)
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(setup_payload)}"

    # Start PyHAP driver in background task safely
    driver_task = hass.async_create_background_task(
        driver.async_start(), name=f"apple_homekey_driver_{entry_id}"
    )

    hass.data[DOMAIN][entry_id] = {
        "store": store,
        "driver": driver,
        "driver_task": driver_task,
        "accessory": accessory,
        "setup_payload": setup_payload,
        "qr_image_url": qr_image_url,
    }

    # Send Persistent Notification with Setup Code & QR Code
    notification_msg = (
        f"### 🔑 Apple HomeKey Virtual Lock Ready for Pairing\n\n"
        f"**Accessory Name:** `{name}`\n\n"
        f"**Setup PIN Code:** `{setup_code}`\n\n"
        f"**Setup ID:** `{setup_id}`\n\n"
        f"**HomeKit Setup Payload:** `{setup_payload}`\n\n"
        f"![Scan to Pair with Apple Home]({qr_image_url})\n\n"
        f"**Pairing Instructions:**\n"
        f"1. Open the **Apple Home** app on your iPhone.\n"
        f"2. Tap **+ Add Accessory** and scan the QR Code above (or enter PIN `{setup_code}` manually).\n"
        f"3. Complete the lock setup wizard. Apple will automatically provision HomeKey credentials to this lock.\n"
        f"4. Once paired, download `homekeyc.h` at: `http://<YOUR_HA_IP>:8123{URL_DOWNLOAD_HOMEKEYC}`\n"
    )
    persistent_notification.async_create(
        hass,
        notification_msg,
        title="Apple HomeKey Lock Setup",
        notification_id=f"apple_homekey_pairing_{entry_id}",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_id = entry.entry_id
    data = hass.data[DOMAIN].pop(entry_id, None)

    if data:
        driver: AccessoryDriver = data["driver"]
        try:
            await driver.async_stop()
        except Exception as err:
            _LOGGER.warning("Error stopping PyHAP driver: %s", err)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok
