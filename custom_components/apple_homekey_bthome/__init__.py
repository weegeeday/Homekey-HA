"""Apple HomeKey Token Extractor integration for Home Assistant."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import urllib.parse
from typing import Any

# Disable Python bytecode (.pyc) writing for this integration
sys.dont_write_bytecode = True

# Auto-purge any stale __pycache__ folder in this component directory on startup
_pycache_path = os.path.join(os.path.dirname(__file__), "__pycache__")
if os.path.exists(_pycache_path):
    try:
        shutil.rmtree(_pycache_path, ignore_errors=True)
    except Exception:
        pass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.persistent_notification import async_create as create_persistent_notification
from homeassistant.helpers import config_validation as cv
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

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def generate_mac(entry_id: str) -> str:
    """Generate a unique MAC address from entry_id for HomeKit driver."""
    import hashlib
    digest = hashlib.md5(entry_id.encode("utf-8")).hexdigest()
    return f"06:{digest[0:2]}:{digest[2:4]}:{digest[4:6]}:{digest[6:8]}:{digest[8:10]}"


def format_setup_code(code: str) -> str:
    """Ensure setup_code is in XXX-YY-ZZZ 8-digit hyphenated format."""
    digits = "".join(c for c in code if c.isdigit())
    if len(digits) == 8:
        return f"{digits[0:3]}-{digits[3:5]}-{digits[5:8]}"
    return code


def get_setup_payload(setup_code: str, setup_id: str) -> str:
    """Generate official HomeKit setup payload URI (X-HM://...)."""
    try:
        clean_code = setup_code.replace("-", "")
        code_int = int(clean_code)
        
        # HAP Spec Section 5.3 Payload Bit Layout:
        # Pincode: 27 bits (bits 0..26)
        # Flags: 4 bits (bits 27..30) -> 2 (IP)
        # Category: 8 bits (bits 31..38) -> 6 (Door Lock)
        # Reserved: 4 bits (bits 39..42) -> 0
        # Version: 3 bits (bits 43..45) -> 0
        category = CATEGORY_DOOR_LOCK  # 6
        flags = 2  # IP accessory
        version = 0
        reserved = 0
        
        payload_num = (version << 43) | (reserved << 39) | (category << 31) | (flags << 27) | code_int
        
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        base36 = ""
        n = payload_num
        while n > 0:
            n, rem = divmod(n, 36)
            base36 = alphabet[rem] + base36
        
        base36 = base36.zfill(9)
        return f"X-HM://{base36}{setup_id.upper()}"
    except Exception as err:
        _LOGGER.warning("Error generating HomeKit X-HM payload: %s", err)
        return f"X-HM://0061PS23H{setup_id.upper()}"


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
    setup_code = format_setup_code(entry.data.get(CONF_SETUP_CODE, "111-22-333"))
    setup_id = entry.data.get(CONF_SETUP_ID, "HK12")
    finish_color = entry.data.get(CONF_FINISH_COLOR, DEFAULT_FINISH_COLOR)

    pincode_bytes = setup_code.encode("ascii")

    # Initialize key store and ensure initial Reader Key exists immediately
    store = HomeKeyStore(hass, entry_id)
    await store.async_load()
    store.ensure_reader_key()
    await store.async_save()

    # Automatically save homekeyc.h to /config/homekeyc.h & /config/www/homekeyc.h
    from .generator import save_homekey_header_files
    await hass.async_add_executor_job(save_homekey_header_files, hass, store)

    # Register HTTP View (only once if not already registered)
    if "http_view_registered" not in hass.data[DOMAIN]:
        view = HomeKeyHeaderView(hass)
        hass.http.register_view(view)
        hass.data[DOMAIN]["http_view_registered"] = True

    # Retrieve official AsyncZeroconf instance from Home Assistant
    async_zc = None
    try:
        from homeassistant.components.zeroconf import async_get_async_zeroconf
        async_zc = async_get_async_zeroconf(hass)
    except Exception as err:
        _LOGGER.debug("Could not get HA async zeroconf instance: %s", err)

    mac_address = generate_mac(entry_id)
    state_file = hass.config.path(f".apple_homekey_{entry_id}.state")

    # Get primary local LAN IP address from Home Assistant network component
    local_ip = None
    try:
        from homeassistant.components.network import async_get_source_ip
        local_ip = await async_get_source_ip(hass)
    except Exception as err:
        _LOGGER.debug("Could not get HA source IP: %s", err)

    # Configure PyHAP Driver with HA Zeroconf, LAN IP & Unique MAC
    driver_kwargs: dict[str, Any] = {
        "port": port,
        "persist_file": state_file,
        "pincode": pincode_bytes,
        "loop": hass.loop,
        "mac": mac_address,
        "zeroconf_server": f"homekey-{entry_id[:8]}.local.",
    }
    if local_ip:
        driver_kwargs["advertised_address"] = local_ip

    if async_zc is not None:
        driver_kwargs["async_zeroconf_instance"] = async_zc

    driver = AccessoryDriver(**driver_kwargs)

    if os.path.exists(state_file):
        try:
            driver.load()
        except Exception as err:
            _LOGGER.warning("Error loading PyHAP state file %s: %s", state_file, err)
    else:
        driver.state.mac = mac_address
        driver.state.setup_id = setup_id
        driver.state.pincode = pincode_bytes
        try:
            driver.persist()
        except Exception as err:
            _LOGGER.warning("Error persisting initial PyHAP state: %s", err)

    # Ensure unprovisioned lock stays discoverable for pairing (sf=1)
    if not store.is_provisioned:
        driver.state.paired_clients.clear()

    driver.state.setup_id = setup_id
    driver.state.pincode = pincode_bytes
    driver.setup_srp_verifier()

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

    def _on_driver_task_done(task: Any) -> None:
        if not task.cancelled() and task.exception():
            _LOGGER.error(
                "PyHAP driver background task failed: %s",
                task.exception(),
                exc_info=task.exception(),
            )

    # Start PyHAP driver in background task safely
    driver_task = hass.async_create_background_task(
        driver.async_start(), name=f"apple_homekey_driver_{entry_id}"
    )
    driver_task.add_done_callback(_on_driver_task_done)

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
    create_persistent_notification(
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
