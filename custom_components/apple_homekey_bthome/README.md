# Apple HomeKey Token Extractor Integration (`apple_homekey_bthome`)

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/default)
[![HomeKit](https://img.shields.io/badge/HomeKit-HAP--Python-blue.svg)](https://github.com/ikalchev/HAP-python)

A HACS-compliant Home Assistant custom component that creates a virtual HomeKit lock accessory to extract Apple HomeKey tokens (Reader Private Key `SK.R`, Group ID `GID`, Issuer Public Keys, and Endpoint credentials), formatting them into a downloadable C++ header file (`homekeyc.h`) for ESP32 firmware projects (such as `HomeKey-ESP32` or `DigitalDoorKey`).

---

## 🌟 How It Works

1. **Virtual HomeKit Lock**: The integration creates a virtual HomeKit lock accessory using `HAP-python` that advertises the HomeKit `NFCAccess` service (`UUID: 00000266-...`).
2. **Apple Home Pairing**: You pair your Apple Home app to this virtual lock using the generated **QR Code** or randomized **Setup PIN Code**.
3. **HomeKey Provisioning**: Apple Home automatically generates and provisions your Home's Reader Private Key (`SK.R`) and device endpoint credentials down to the virtual lock via HAP TLV8 characteristics.
4. **Token Interception**: The integration intercepts the cryptographic keys, calculates key derivations (Group Identifier $\text{GID} = \text{SHA-256}(\text{SK.R})[0..7]$ and Endpoint Identifier $\text{Endpoint.ID} = \text{SHA-1}(\text{PK.Endpoint})[0..5]$), and persists them to Home Assistant storage.
5. **C++ Header Export**: Exposes an HTTP API view (`/api/apple_homekey_bthome/homekeyc.h`) to stream a ready-to-use C++ header file formatted for ESP32 compilers.

---

## 🚀 Installation

### Option A: Via HACS (Recommended)

1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add repository URL: `https://github.com/weegeeday/Homekey-HA` with Category **Integration**.
4. Search for **Apple HomeKey Token Extractor** and click **Download**.
5. Restart Home Assistant.

### Option B: Manual Installation

1. Copy the `custom_components/apple_homekey_bthome/` folder into your Home Assistant `<config>/custom_components/` directory.
2. Restart Home Assistant.

---

## ⚙️ Configuration & Setup

1. In Home Assistant, go to **Settings** -> **Devices & Services** -> **Add Integration**.
2. Search for **Apple HomeKey Token Extractor**.
3. The setup wizard will automatically generate:
   - A random **Setup PIN Code** (e.g. `123-45-678`)
   - A random **Setup ID** (e.g. `HK92`)
   - An available **HAP Port** (e.g. `51827`)
   - Optional **Hardware Finish** color for your key card icon in Apple Wallet (Black, Silver, Gold, Tan).
4. Click **Submit**.

---

## 📲 Pairing with Apple Home

1. Open the **Apple Home** app on your iPhone or iPad.
2. Tap **+** -> **Add Accessory**.
3. Scan the QR code displayed in the Home Assistant persistent notification or on the Lock entity card. (Alternatively, tap *More options* -> *Enter code* and enter the 8-digit setup PIN).
4. Follow the prompt to name your lock and assign it to a room.
5. Apple Home will automatically issue a HomeKey pass to your Apple Wallet!

---

## 💾 Downloading `homekeyc.h`

Once paired with Apple Home:

Navigate to the download endpoint in your web browser:
```http
http://<YOUR_HOME_ASSISTANT_IP>:8123/api/apple_homekey_bthome/homekeyc.h
```

Or download via `curl`:
```bash
curl -O http://<YOUR_HOME_ASSISTANT_IP>:8123/api/apple_homekey_bthome/homekeyc.h
```

> [!NOTE]
> If you attempt to download `homekeyc.h` before pairing with Apple Home, the server will return an HTTP 400 JSON error explaining that key provisioning is waiting for Apple Home pairing.

---

## 🔐 Exported C++ Header Structure (`homekeyc.h`)

```cpp
#ifndef HOMEKEYC_H
#define HOMEKEYC_H

#include <stdint.h>
#include <stddef.h>

// Reader Private Key (32-byte SECP256R1 SK.R)
const uint8_t HOMEKEY_READER_PRIVATE_KEY[32] = { ... };

// Reader Public Key (65-byte uncompressed SECP256R1 PK.R: 0x04 || X || Y)
const uint8_t HOMEKEY_READER_PUBLIC_KEY[65] = { ... };

// Reader Public Key X-Coordinate (32 bytes PK.R_X)
const uint8_t HOMEKEY_READER_PUBLIC_KEY_X[32] = { ... };

// Reader Group Identifier (8-byte GID = SHA-256(SK.R)[0..7])
const uint8_t HOMEKEY_READER_GROUP_ID[8] = { ... };

// Reader Sub-Identifier (8 bytes)
const uint8_t HOMEKEY_READER_SUB_ID[8] = { ... };

#define HOMEKEY_ENDPOINT_COUNT 1

typedef struct {
    uint8_t issuer_id[8];
    uint8_t endpoint_id[6];
    uint8_t public_key[65];
    uint8_t public_key_x[32];
} homekey_endpoint_t;

const homekey_endpoint_t HOMEKEY_ENDPOINTS[HOMEKEY_ENDPOINT_COUNT] = { ... };

#endif // HOMEKEYC_H
```

---

## 🛡️ Privacy & Security

`homekeyc.h` contains secret cryptographic private keys (`SK.R`) that allow contactless unlock access to your HomeKey configuration. Keep your `homekeyc.h` file private and never commit it to public repositories.
