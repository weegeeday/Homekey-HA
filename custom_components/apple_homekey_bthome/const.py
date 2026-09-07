"""Constants for the Apple HomeKey Token Extractor integration."""

DOMAIN = "apple_homekey_bthome"
MANUFACTURER = "Apple / Homekey-HA"
MODEL = "Virtual HomeKey Lock"

# Configuration options
CONF_NAME = "name"
CONF_PORT = "port"
CONF_SETUP_CODE = "setup_code"
CONF_SETUP_ID = "setup_id"
CONF_FINISH_COLOR = "finish_color"

DEFAULT_NAME = "HomeKey Virtual Lock"
DEFAULT_START_PORT = 51827
DEFAULT_FINISH_COLOR = "black"

# HomeKit HAP Category ID for Door Lock
CATEGORY_DOOR_LOCK = 6

# HomeKit NFCAccess Service & Characteristic UUIDs
SERVICE_NFC_ACCESS = "00000266-0000-1000-8000-0026BB765291"
CHAR_CONFIGURATION_STATE = "00000263-0000-1000-8000-0026BB765291"
CHAR_NFC_ACCESS_CONTROL_POINT = "00000264-0000-1000-8000-0026BB765291"
CHAR_NFC_ACCESS_SUPPORTED_CONFIG = "00000265-0000-1000-8000-0026BB765291"
CHAR_HARDWARE_FINISH = "0000026C-0000-1000-8000-0026BB765291"

# NFCAccessSupportedConfiguration static payload
# Tag 0x01 = 16, Tag 0x02 = 16
DEFAULT_SUPPORTED_CONFIG = bytes([0x01, 0x01, 0x10, 0x02, 0x01, 0x10])

# Hardware Finish TLV8 Payloads
HARDWARE_FINISHES = {
    "black": bytes([0x01, 0x04, 0xCE, 0xD5, 0xDA, 0x00]),
    "silver": bytes([0x01, 0x04, 0xAA, 0xD6, 0xEC, 0x00]),
    "gold": bytes([0x01, 0x04, 0xE3, 0xE3, 0xE3, 0x00]),
    "tan": bytes([0x01, 0x04, 0x00, 0x00, 0x00, 0x00]),
}

# Storage constants
STORAGE_KEY = "apple_homekey_bthome_data"
STORAGE_VERSION = 1

# Download API view
URL_DOWNLOAD_HOMEKEYC = "/api/apple_homekey_bthome/homekeyc.h"
