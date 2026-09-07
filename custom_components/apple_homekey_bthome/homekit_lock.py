"""PyHAP Accessory implementation for Virtual HomeKit Lock with HomeKey support."""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any

from pyhap.accessory import Accessory
from pyhap.characteristic import HAP_FORMAT_DEFAULTS, Characteristic
from pyhap.const import CATEGORY_DOOR_LOCK
from pyhap.service import Service

# Ensure PyHAP HAP_FORMAT_DEFAULTS contains 'tlv8' format default
if "tlv8" not in HAP_FORMAT_DEFAULTS:
    HAP_FORMAT_DEFAULTS["tlv8"] = ""

from .const import (
    CHAR_CONFIGURATION_STATE,
    CHAR_HARDWARE_FINISH,
    CHAR_NFC_ACCESS_CONTROL_POINT,
    CHAR_NFC_ACCESS_SUPPORTED_CONFIG,
    DEFAULT_SUPPORTED_CONFIG,
    HARDWARE_FINISHES,
    MANUFACTURER,
    MODEL,
    SERVICE_NFC_ACCESS,
)
from .tlv import decode_tlv8_dict, encode_tlv8

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .storage import HomeKeyStore

_LOGGER = logging.getLogger(__name__)


class ConfigurationStateChar(Characteristic):
    """ConfigurationState characteristic for NFCAccess service."""

    def __init__(self, service: Service) -> None:
        """Initialize ConfigurationState characteristic."""
        super().__init__(
            "ConfigurationState",
            CHAR_CONFIGURATION_STATE,
            {
                "format": "uint16",
                "Format": "uint16",
                "perms": ["pr", "ev"],
                "Permissions": ["pr", "ev"],
                "minValue": 0,
                "maxValue": 65535,
                "stepValue": 1,
            },
            service,
        )

    def _get_default_value(self) -> int:
        """Return default configuration state integer."""
        return 1


class NFCAccessControlPointChar(Characteristic):
    """NFCAccessControlPoint characteristic for HomeKey provisioning TLV pipeline."""

    def __init__(self, service: Service) -> None:
        """Initialize NFCAccessControlPoint characteristic."""
        super().__init__(
            "NFCAccessControlPoint",
            CHAR_NFC_ACCESS_CONTROL_POINT,
            {
                "format": "tlv8",
                "Format": "tlv8",
                "perms": ["pr", "pw", "ev"],
                "Permissions": ["pr", "pw", "ev"],
            },
            service,
        )

    def _get_default_value(self) -> bytes:
        """Return default empty TLV bytes."""
        return b""


class NFCAccessSupportedConfigChar(Characteristic):
    """NFCAccessSupportedConfiguration characteristic."""

    def __init__(self, service: Service) -> None:
        """Initialize NFCAccessSupportedConfiguration characteristic."""
        super().__init__(
            "NFCAccessSupportedConfiguration",
            CHAR_NFC_ACCESS_SUPPORTED_CONFIG,
            {
                "format": "tlv8",
                "Format": "tlv8",
                "perms": ["pr"],
                "Permissions": ["pr"],
            },
            service,
        )

    def _get_default_value(self) -> bytes:
        """Return static supported configuration payload."""
        return DEFAULT_SUPPORTED_CONFIG


class HardwareFinishChar(Characteristic):
    """HardwareFinish characteristic for key card rendering color in Apple Wallet."""

    def __init__(self, service: Service) -> None:
        """Initialize HardwareFinish characteristic."""
        super().__init__(
            "HardwareFinish",
            CHAR_HARDWARE_FINISH,
            {
                "format": "tlv8",
                "Format": "tlv8",
                "perms": ["pr"],
                "Permissions": ["pr"],
            },
            service,
        )

    def _get_default_value(self) -> bytes:
        """Return default hardware finish payload."""
        return HARDWARE_FINISHES["black"]


class NFCAccessService(Service):
    """NFCAccess HomeKit Service."""

    def __init__(self) -> None:
        """Initialize NFCAccess service."""
        super().__init__(SERVICE_NFC_ACCESS, "NFCAccess")
        self.char_config_state = ConfigurationStateChar(self)
        self.char_nfc_control_point = NFCAccessControlPointChar(self)
        self.char_nfc_supported = NFCAccessSupportedConfigChar(self)

        self.add_characteristic(self.char_config_state)
        self.add_characteristic(self.char_nfc_control_point)
        self.add_characteristic(self.char_nfc_supported)


class HomeKeyLockAccessory(Accessory):
    """Virtual HomeKit Lock accessory implementing HomeKey NFCAccess TLV engine."""

    category = CATEGORY_DOOR_LOCK

    def __init__(
        self,
        driver: Any,
        name: str,
        store: HomeKeyStore,
        finish_color: str = "black",
        aid: int = 1,
        hass: HomeAssistant | None = None,
    ) -> None:
        """Initialize virtual HomeKit lock accessory."""
        super().__init__(driver, name, aid=aid)
        self.store = store
        self.hass = hass
        self.finish_color = finish_color

        # Set Accessory Information
        info_service = self.get_service("AccessoryInformation")
        info_service.get_characteristic("Manufacturer").set_value(MANUFACTURER)
        info_service.get_characteristic("Model").set_value(MODEL)
        info_service.get_characteristic("SerialNumber").set_value("HK-ESP32-VIRTUAL")
        info_service.get_characteristic("FirmwareRevision").set_value("2.0.0")

        # Add HardwareFinish characteristic to AccessoryInformation
        finish_bytes = HARDWARE_FINISHES.get(finish_color, HARDWARE_FINISHES["black"])
        finish_char = HardwareFinishChar(info_service)
        finish_char.set_value(finish_bytes)
        info_service.add_characteristic(finish_char)

        # Lock Mechanism Service (Primary Service for Door Lock)
        self.serv_lock_mech = self.add_preload_service("LockMechanism")
        self.char_lock_current = self.serv_lock_mech.get_characteristic("LockCurrentState")
        self.char_lock_target = self.serv_lock_mech.get_characteristic("LockTargetState")
        
        # Default state: Locked (1)
        self.char_lock_current.set_value(1)
        self.char_lock_target.set_value(1)
        self.char_lock_target.setter_callback = self.set_lock_target

        # Lock Management Service
        self.serv_lock_mgmt = self.add_preload_service("LockManagement")
        self.serv_lock_mgmt.get_characteristic("Version").set_value("2.0")
        try:
            self.serv_lock_mgmt.get_characteristic("LockControlPoint").setter_callback = lambda val: None
        except Exception:
            pass

        # NFC Access Service
        self.serv_nfc = NFCAccessService()
        self.add_service(self.serv_nfc)

        self.char_config_state = self.serv_nfc.char_config_state
        self.char_nfc_control_point = self.serv_nfc.char_nfc_control_point
        self.char_nfc_supported = self.serv_nfc.char_nfc_supported

        # Set static values and initial configuration state
        self.char_nfc_supported.set_value(DEFAULT_SUPPORTED_CONFIG)
        self.char_config_state.set_value(self.store.configuration_state)

        # Set setter callback for NFCAccessControlPoint
        self.char_nfc_control_point.setter_callback = self.handle_nfc_access_control_point

    def set_lock_target(self, value: int) -> None:
        """Handle lock target state changes from HomeKit."""
        _LOGGER.info("HomeKit lock target state set to %d", value)
        self.char_lock_current.set_value(value)
        self.char_lock_target.set_value(value)

    def handle_nfc_access_control_point(self, value: Any) -> None:
        """Handle TLV writes to NFCAccessControlPoint from Apple Home."""
        _LOGGER.debug("Received NFCAccessControlPoint write payload: %s", type(value))

        raw_bytes = b""
        if isinstance(value, str):
            try:
                raw_bytes = base64.b64decode(value)
            except Exception:
                raw_bytes = value.encode("utf-8")
        elif isinstance(value, (bytes, bytearray)):
            raw_bytes = bytes(value)

        if not raw_bytes:
            _LOGGER.warning("Empty NFCAccessControlPoint payload received")
            return

        try:
            response_tlv = self._process_nfc_tlv(raw_bytes)
            if response_tlv:
                # Update characteristic value to response TLV and notify subscribers
                self.char_nfc_control_point.set_value(response_tlv)
            
            # Notify updated configuration state counter
            self.char_config_state.set_value(self.store.configuration_state)
        except Exception as err:
            _LOGGER.error("Error processing NFCAccessControlPoint TLV: %s", err, exc_info=True)

    def _process_nfc_tlv(self, data: bytes) -> bytes:
        """Process incoming TLV payload and update key store."""
        top_tlv = decode_tlv8_dict(data)
        op_bytes = top_tlv.get(0x01, b"\x00")
        op_val = op_bytes[0] if op_bytes else 0

        _LOGGER.info("Processing HomeKey NFCAccess TLV write: Operation=0x%02X", op_val)
        response_bytes = b""

        # 1. Reader Key Request (Tag 0x06)
        if 0x06 in top_tlv:
            rkr_tlv = decode_tlv8_dict(top_tlv[0x06])
            
            if op_val == 0x02:  # Write Reader Key
                sk_r = rkr_tlv.get(0x02)  # 32-byte SECP256R1 Private Key
                sub_id = rkr_tlv.get(0x03, b"\x00" * 8)
                if sk_r and len(sk_r) == 32:
                    self.store.set_reader_key(sk_r, sub_id)
                    self._schedule_save()
                    resp_sub = encode_tlv8({0x02: bytes([0x00])})  # Status 0x00 Success
                    response_bytes = encode_tlv8({0x07: resp_sub})
                    _LOGGER.info("Successfully provisioned Reader Private Key (SK.R)")
                else:
                    _LOGGER.error("Invalid Reader Private Key length received: %s", len(sk_r) if sk_r else 0)

            elif op_val == 0x01:  # Read Reader Key
                gid = self.store.gid or (b"\x00" * 8)
                resp_sub = encode_tlv8({0x01: gid, 0x02: bytes([0x00])})
                response_bytes = encode_tlv8({0x07: resp_sub})
                _LOGGER.info("Responded to Read Reader Key query with GID=%s", gid.hex())

            elif op_val == 0x03:  # Remove Reader Key
                self.store.remove_reader_key()
                self._schedule_save()
                resp_sub = encode_tlv8({0x02: bytes([0x00])})
                response_bytes = encode_tlv8({0x07: resp_sub})
                _LOGGER.info("Removed Reader Key")

        # 2. Device Credential Request (Tag 0x04)
        elif 0x04 in top_tlv:
            dcr_tlv = decode_tlv8_dict(top_tlv[0x04])

            if op_val == 0x02:  # Provision Device Credential
                pub_key_64 = dcr_tlv.get(0x02)  # 64-byte raw X||Y public key
                issuer_id = dcr_tlv.get(0x03)  # 8-byte Issuer ID
                if pub_key_64 and len(pub_key_64) == 64 and issuer_id and len(issuer_id) == 8:
                    ep_record = self.store.add_endpoint(issuer_id, pub_key_64)
                    self._schedule_save()
                    resp_sub = encode_tlv8({0x02: issuer_id, 0x03: bytes([0x00])})
                    response_bytes = encode_tlv8({0x05: resp_sub})
                    _LOGGER.info("Successfully provisioned Device Endpoint %s", ep_record["endpoint_id"])
                else:
                    _LOGGER.error("Invalid Device Credential parameters received")

            elif op_val == 0x03:  # Remove Device Credential
                issuer_id = dcr_tlv.get(0x03)
                endpoint_id = dcr_tlv.get(0x05) or dcr_tlv.get(0x02)
                if issuer_id:
                    self.store.remove_endpoint(issuer_id, endpoint_id)
                    self._schedule_save()
                resp_sub = encode_tlv8({0x03: bytes([0x00])})
                response_bytes = encode_tlv8({0x05: resp_sub})
                _LOGGER.info("Removed Device Credential")

        return response_bytes

    def _schedule_save(self) -> None:
        """Schedule persistent store saving on Home Assistant event loop."""
        if self.hass:
            self.hass.async_create_task(self.store.async_save())
