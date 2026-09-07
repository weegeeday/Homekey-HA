# Apple HomeKey Protocol Specification & Communication Architecture

This document provides a comprehensive, end-to-end technical specification of the **Apple HomeKey** protocol based on the implementation in `HomeKey-ESP32` and `DigitalDoorKey`. It covers all protocol layers, data structures, cryptographic operations, TLV tags, NFC APDUs, and HomeKit HAP services required to build a fully functional HomeKey-compatible smart lock from scratch.

---

## Table of Contents
1. [Architecture Overview](#1-architecture-overview)
2. [HomeKit HAP Provisioning & Key Management Layer](#2-homekit-hap-provisioning--key-management-layer)
   - [HAP Services and Characteristics](#hap-services-and-characteristics)
   - [NFC Access Control Point Protocol (`NFCAccessControlPoint`)](#nfc-access-control-point-protocol-nfcaccesscontrolpoint)
   - [Provisioning Sequences & Data Structures](#provisioning-sequences--data-structures)
3. [NFC Air Interface Layer](#3-nfc-air-interface-layer)
   - [Enhanced Contactless Polling (ECP)](#enhanced-contactless-polling-ecp)
   - [ISO/IEC 14443-4 & ISO 7816-4 APDU Transport](#isoiec-14443-4--iso-7816-4-apdu-transport)
4. [Digital Door Key (DDK) Protocol & Handshake Sequences](#4-digital-door-key-ddk-protocol--handshake-sequences)
   - [Flow Step 1: Applet Selection](#flow-step-1-applet-selection)
   - [Flow Step 2: AUTH0 (Initial Handshake)](#flow-step-2-auth0-initial-handshake)
   - [Flow Step 3: Fast Authentication Flow (0-RTT Token Resume)](#flow-step-3-fast-authentication-flow-0-rtt-token-resume)
   - [Flow Step 4: Standard Authentication Flow (ECDH + SCB Channel)](#flow-step-4-standard-authentication-flow-ecdh--scb-channel)
   - [Flow Step 5: Attestation Authentication Flow (ISO 18013 / Initial Device Registration)](#flow-step-5-attestation-authentication-flow-iso-18013--initial-device-registration)
5. [Cryptographic Reference & Key Schedule](#5-cryptographic-reference--key-schedule)
   - [Key Hierarchy & Storage Summary](#key-hierarchy--storage-summary)
   - [Derivation Algorithms & Formats](#derivation-algorithms--formats)
6. [Implementation Checklist for Custom Readers](#6-implementation-checklist-for-custom-readers)

---

## 1. Architecture Overview

Apple HomeKey relies on a **dual-channel system architecture**:

```
+-------------------------------------------------------------------------+
|                              Apple iPhone / Watch                       |
+------------------------------------+------------------------------------+
                                     |
               HomeKit (HAP)         | NFC (ISO 14443-4 APDU & ECP)
            IP / Thread / BLE        | 13.56 MHz Contactless
                                     |
+------------------------------------+------------------------------------+
|                           HomeKey Smart Lock Reader                     |
|                                                                         |
|  +---------------------------+     |     +---------------------------+  |
|  |  HomeKit Provisioning     |     |     | NFC Contactless Engine    |  |
|  |  (HAP Services / TLV8)    |<----+---->| (DDK / SCB / ISO 18013)   |  |
|  +-------------+-------------+           +-------------+-------------+  |
|                |                                       |                |
|                +-------------------+-------------------+                |
|                                    |                                    |
|                         +----------v----------+                         |
|                         | NVS Credential Store|                         |
|                         | (Reader / Endpoint) |                         |
|                         +---------------------+                         |
+-------------------------------------------------------------------------+
```

1. **HomeKit HAP Channel (IP / BLE / Thread)**:
   - Used when pairing the lock to an Apple Home Hub.
   - Exchanges Reader Private/Public Keys (`SK.R`, `PK.R`).
   - Provisions device credentials (Issuer Public Keys `PK.Issuer` and Endpoint Public Keys `PK.Endpoint`).
2. **NFC Contactless Channel (13.56 MHz)**:
   - Emits **Enhanced Contactless Polling (ECP)** frames to wake up Apple Wallet without user interaction.
   - Executes the **Digital Door Key (DDK)** APDU protocol over ISO/IEC 14443-4.
   - Performs rapid authentication (Fast Auth: ~30–50 ms; Standard/Attestation Auth: ~100–300 ms).

---

## 2. HomeKit HAP Provisioning & Key Management Layer

### HAP Services and Characteristics

To support HomeKey, a HomeKit Lock accessory MUST expose the following HAP services:

| Service Name | Service UUID | Description |
| :--- | :--- | :--- |
| `NFCAccess` | `00000266-0000-1000-8000-0026BB765291` | Primary HomeKey configuration service |
| `LockManagement` | `00000044-0000-1000-8000-0026BB765291` | HAP lock control and version management |
| `LockMechanism` | `00000045-0000-1000-8000-0026BB765291` | Lock state control (`LockCurrentState`, `LockTargetState`) |
| `AccessoryInformation`| `0000003E-0000-1000-8000-0026BB765291` | Hardware metadata including key color finish |

#### `NFCAccess` Service Characteristics

1. **`ConfigurationState`** (`UUID: 00000263-...`, Format: `UINT16`, Permissions: Read, Event Notification):
   - Increments whenever credentials or reader keys change in memory.
2. **`NFCAccessControlPoint`** (`UUID: 00000264-...`, Format: `TLV8`, Permissions: Read, Write, Event Notification):
   - The primary command pipeline for reading reader keys, writing reader keys, provisioning device credentials, and revoking credentials.
3. **`NFCAccessSupportedConfiguration`** (`UUID: 00000265-...`, Format: `TLV8`, Permissions: Read):
   - Static capability payload. Standard initialization TLV bytes: `01 01 10 02 01 10` (Tag `0x01` = 16, Tag `0x02` = 16).

#### `AccessoryInformation` Service Additions

- **`HardwareFinish`** (`UUID: 0000026C-...`, Format: `TLV8`, Permissions: Read):
  - Defines the key card icon color rendered in Apple Wallet.
  - TLV8 Payload: `Tag 0x01, Len 0x04, Value [4 Bytes Finish Code], 0x00`.
  - Common color values:
    - **Black**: `01 04 CE D5 DA 00`
    - **Silver**: `01 04 AA D6 EC 00`
    - **Gold**: `01 04 E3 E3 E3 00`
    - **Tan**: `01 04 00 00 00 00`

---

### NFC Access Control Point Protocol (`NFCAccessControlPoint`)

The `NFCAccessControlPoint` payload is encoded as a nested **TLV8** structure.

#### Top-Level TLV Tags

| Tag Hex | Constant Name | Description |
| :--- | :--- | :--- |
| `0x01` | `kReader_Operation` | Requested operation: `0x01` = Read, `0x02` = Write, `0x03` = Remove |
| `0x04` | `kReader_Device_Credential_Request` | Sub-TLV for provisioning or removing endpoint credentials |
| `0x05` | `kReader_Device_Credential_Response` | Sub-TLV response for endpoint credential operations |
| `0x06` | `kReader_Reader_Key_Request` | Sub-TLV for reading or writing reader private/public keys |
| `0x07` | `kReader_Reader_Key_Response` | Sub-TLV response for reader key operations |

---

### Provisioning Sequences & Data Structures

#### 1. Write Reader Key (`Operation = 0x02`, `RKR = 0x06`)
Sent by Apple Home when the lock is paired or assigned to a Home.

**Request Payload Breakdown:**
- Outer TLV: `Tag 0x01 (Operation) = 0x02`, `Tag 0x06 (RKR) = [Sub-TLV]`
- Sub-TLV (`Tag 0x06`):
  - `Tag 0x02` (`kReader_Req_Reader_Private_Key`): 32-byte SECP256R1 Private Key (`SK.R`).
  - `Tag 0x03` (`kReader_Req_Identifier`): 8-byte Reader Sub-Identifier / Unique Identifier.

**Lock Processing:**
1. Derive Reader Public Key `PK.R` (65 bytes uncompressed: `0x04 || X || Y`) from `SK.R`.
2. Extract 32-byte X-coordinate `PK.R_X`.
3. Compute 8-byte **Group Identifier (`GID`)**:
   $$\text{GID} = \text{SHA-256}(\text{SK.R})[0..7]$$
4. Persist `SK.R`, `PK.R`, `PK.R_X`, Sub-Identifier, and `GID` to NVS.
5. Re-generate ECP broadcast frame with the new `GID`.

**Response Payload:**
- Outer TLV: `Tag 0x07 (RKR Response)` containing Sub-TLV:
  - `Tag 0x02` (`kReader_Res_Status`): `0x00` (Success).

---

#### 2. Read Reader Key (`Operation = 0x01`, `RKR = 0x06`)
Sent by Apple Home to verify if the lock already possesses a Reader Key.

**Request Payload:** `Tag 0x01 = 0x01`, `Tag 0x06 = []`.

**Response Payload:**
- Outer TLV: `Tag 0x07` containing Sub-TLV:
  - `Tag 0x01` (`kReader_Res_Key_Identifier`): Stored 8-byte `GID`.
  - `Tag 0x02` (`kReader_Res_Status`): `0x00` (Success).

---

#### 3. Provision Device Credential (`Operation = 0x02`, `DCR = 0x04`)
Sent by Apple Home to provision an iPhone or Apple Watch pass key on the lock.

**Request Payload Breakdown:**
- Outer TLV: `Tag 0x01 = 0x02`, `Tag 0x04 (DCR) = [Sub-TLV]`
- Sub-TLV (`Tag 0x04`):
  - `Tag 0x01` (`kDevice_Req_Key_Type`): `0x01` (ECC SECP256R1).
  - `Tag 0x02` (`kDevice_Req_Public_Key`): 64-byte raw X\|\|Y public key of device endpoint.
  - `Tag 0x03` (`kDevice_Req_Issuer_Key_Identifier`): 8-byte Issuer Key Identifier (`Issuer.ID`).

**Lock Processing:**
1. Prefix 64-byte public key with `0x04` to form 65-byte uncompressed `PK.Endpoint`.
2. Compute 6-byte **Endpoint Identifier (`Endpoint.ID`)**:
   $$\text{Endpoint.ID} = \text{SHA-1}(\text{PK.Endpoint})[0..5]$$
3. Extract 32-byte X-coordinate `PK.Endpoint_X`.
4. Locate or create Issuer matching `Issuer.ID`.
5. Add Endpoint record under Issuer with `counter = 0`, `key_type = 0x01`.
6. Save to NVS.

**Response Payload:**
- Outer TLV: `Tag 0x05` containing Sub-TLV:
  - `Tag 0x02` (`kDevice_Res_Issuer_Key_Identifier`): `Issuer.ID` (8 bytes).
  - `Tag 0x03` (`kDevice_Res_Status`): `0x00` (Success), `0x02` (Duplicate), or `0x03` (Does Not Exist).

---

#### 4. Remove Credential / Reader Key (`Operation = 0x03`)
- **Remove Reader Key**: Received with `Tag 0x06`. Clears reader identity in NVS and returns `07 03 02 01 00`.
- **Remove Device Credential**: Received with `Tag 0x04` containing `Issuer.ID` (`0x03`) and optional `Key.ID` (`0x05`) or `Public.Key` (`0x02`). Erases endpoint(s) from NVS and returns status `0x00`.

---

## 3. NFC Air Interface Layer

### Enhanced Contactless Polling (ECP)

To allow iPhones and Apple Watches to recognize the lock instantly (even in power reserve mode), the reader MUST continuously broadcast an **ECP Frame** before establishing an ISO 14443-4 link.

#### ECP Frame Structure (18 Bytes Total)

| Byte Offset | Field | Value / Description |
| :--- | :--- | :--- |
| `0..1` | Frame Header | `0x6A, 0x02` (ECP Format, Subtype 2) |
| `2..3` | Terminal Subtype | `0xCB, 0x02` (Access Control Reader) |
| `4..5` | Reader Capabilities | `0x06, 0x02` |
| `6..7` | HomeKey Protocol Version | `0x11, 0x00` (HomeKey v2.0) |
| `8..15` | Reader Group Identifier | 8-byte `GID` (derived from `SHA-256(SK.R)[0..7]`) |
| `16..17` | CRC-16A | ISO 14443-A CRC calculated over bytes 0..15 |

*Note: If no Reader Key is provisioned yet, `GID` bytes `8..15` should be filled with zeros.*

---

### ISO/IEC 14443-4 & ISO 7816-4 APDU Transport

Once an Apple device enters the RF field after ECP detection:
1. The reader executes standard ISO 14443-A anticollision (ATQA, SAK, UID).
2. The reader sends RATS (Request for Answer to Select).
3. Data frames are exchanged using standard **ISO 7816-4 Command/Response APDU** format:

$$\text{Command APDU: } \underbrace{\text{CLA}}_{\text{1B}} \, \underbrace{\text{INS}}_{\text{1B}} \, \underbrace{\text{P1}}_{\text{1B}} \, \underbrace{\text{P2}}_{\text{1B}} \, [\underbrace{\text{Lc}}_{\text{1B}} \, \underbrace{\text{Data}}_{\text{Lc Bytes}}] \, [\underbrace{\text{Le}}_{\text{1B}}]$$

$$\text{Response APDU: } [\underbrace{\text{Data}}_{\text{N Bytes}}] \, \underbrace{\text{SW1}}_{\text{1B}} \, \underbrace{\text{SW2}}_{\text{1B}}$$

- **Success Status Word**: `SW1 = 0x90`, `SW2 = 0x00`.

---

## 4. Digital Door Key (DDK) Protocol & Handshake Sequences

The NFC authentication flow follows a 3-tier ladder architecture:
1. **Fast Auth (0-RTT)**: Uses persistent symmetric key saved from prior Standard Auth.
2. **Standard Auth (1-RTT)**: Ephemeral ECDH + X9.63 KDF + SCB encrypted channel + ECDSA signature verification.
3. **Attestation Auth (Initial Registration)**: Encrypted ISO 18013 session channel + COSE_Sign1 certificate verification.

```
       [ NFC Tag Detected ]
                 |
         SELECT DDK Applet
                 |
          Send AUTH0 APDU
                 |
      +----------+----------+
      |                      |
[ Fast Auth ]        [ Standard Auth ]
(Cryptogram Match?)   (ECDH + Signature)
      |                      |
      +---- PASS / FAIL <----+
                 |
        (If Unknown Endpoint)
                 |
       [ Attestation Auth ]
     (ISO 18013 CBOR Certificate)
```

---

### Flow Step 1: Applet Selection

- **Command APDU**:
  - `CLA = 0x00`, `INS = 0xA4`, `P1 = 0x04`, `P2 = 0x00`
  - `Lc = 0x07`
  - `Data = A0 00 00 08 58 01 01` (Digital Door Key AID)
  - `Le = 0x00`
- **Response Data**:
  - TLV payload containing supported protocol versions (`Tag 0x5C`). Must contain `02 00` (HomeKey v2.0).

---

### Flow Step 2: AUTH0 (Initial Handshake)

- **Command APDU**:
  - `CLA = 0x80`, `INS = 0x80`
  - `P1 = Flags0` (`0x01` for FAST target, `0x00` for STANDARD target)
  - `P2 = Flags1` (Authentication Policy)
  - `Data` (Concatenated Simple TLVs):
    - `Tag 0x5C` (Protocol Version): `02 00`
    - `Tag 0x87` (Reader Ephemeral Public Key `PK.R_eph`): 65-byte uncompressed SECP256R1 key generated per transaction.
    - `Tag 0x4C` (Transaction ID): 16 cryptographically random bytes.
    - `Tag 0x4D` (Reader Identifier): 8-byte stored Reader Sub-Identifier.

- **Response APDU**:
  - `Tag 0x86` (`kEndpoint_Public_Key`): 65-byte Endpoint Ephemeral Public Key (`PK.E_eph`).
  - `Tag 0x9D` (`kAuth0_Cryptogram`): 16-byte Fast Auth Cryptogram (present if device supports Fast Auth).

---

### Flow Step 3: Fast Authentication Flow (0-RTT Token Resume)

If `Flags0 == 0x01` and `Tag 0x9D` is present in the AUTH0 response:

#### 1. Construct Fast Salt
Concatenate the following fields in exact order:
1. Reader Static Public Key X-coord `PK.R_X` (32 bytes)
2. ASCII string `"VolatileFast"` (12 bytes)
3. Reader Sub-Identifier (8 bytes)
4. Stored Endpoint Public Key X-coord `PK.Endpoint_X` (32 bytes)
5. Transport Kind `0x01` (NFC, 1 byte)
6. Supported Versions header `5C 04 02 00 01 00` (6 bytes)
7. Tag `0x5C` (1 byte)
8. Version Length `0x02` (1 byte)
9. Version `02 00` (2 bytes)
10. Reader Ephemeral Public Key X-coord `PK.R_eph_X` (32 bytes)
11. Transaction ID (16 bytes)
12. `Flags0` (1 byte)
13. `Flags1` (1 byte)
14. Endpoint Ephemeral Public Key X-coord `PK.E_eph_X` (32 bytes)

#### 2. HKDF Derivation
Calculate 58 bytes output key material (`OKM`):
$$\text{OKM} = \text{HKDF-SHA256}(\text{ikm} = \text{persistent\_key}, \text{salt} = \text{Fast Salt}, \text{info} = "")$$

#### 3. Cryptogram Verification
- Compare `OKM[0..15]` against the 16-byte `Tag 0x9D` cryptogram received in AUTH0 using constant-time comparison.
- **If match**: Authentication SUCCESS!
- Send Control Flow APDU: `80 3C 01 00` (`CLA = 0x80`, `INS = 0x3C`, `P1 = 0x01`, `P2 = 0x00`).
- Unlock door immediately (~30–50 ms execution time).

---

### Flow Step 4: Standard Authentication Flow (ECDH + SCB Channel)

If Fast Auth fails or is skipped:

#### 1. Ephemeral ECDH & Shared Secret
Compute SECP256R1 ECDH shared secret (32 bytes):
$$\text{SharedKey} = \text{ECDH}(\text{SK.R\_eph}, \text{PK.E\_eph})$$

#### 2. ANSI X9.63 Key Derivation
Derive 32-byte `DerivedKey` using ANSI X9.63 KDF with SHA-256 and Transaction ID as shared info:
$$\text{DerivedKey} = \text{X963KDF-SHA256}(\text{SharedKey}, \text{shared\_info} = \text{Transaction\_ID})$$

#### 3. Derive Persistent & Volatile Keys via HKDF-SHA256

Construct `Standard Salt` template:
$$\text{Standard Salt} = \text{PK.R\_eph\_X} \,\|\, \text{PK.E\_eph\_X} \,\|\, \text{Transaction\_ID} \,\|\, \text{TransportKind (0x01)} \,\|\, \text{Flags0} \,\|\, \text{Flags1} \,\|\, \text{Context} \,\|\, 0\times5C \,\|\, 0\times02 \,\|\, 02\,00 \,\|\, \text{SupportedVersions}$$

1. **Persistent Key** (32 bytes):
   $$\text{persistent\_key} = \text{HKDF-SHA256}(\text{ikm} = \text{DerivedKey}, \text{salt} = \text{Standard Salt with Context } \text{"Persistent"})$$
2. **Volatile Key** (48 bytes):
   $$\text{volatile\_key} = \text{HKDF-SHA256}(\text{ikm} = \text{DerivedKey}, \text{salt} = \text{Standard Salt with Context } \text{"Volatile"})$$

Splitting the 48-byte `volatile_key`:
- `K.enc` = bytes `0..15` (16 bytes AES-128 encryption key)
- `K.mac` = bytes `16..31` (16 bytes AES-128 command CMAC key)
- `K.rmac` = bytes `32..47` (16 bytes AES-128 response CMAC key)

#### 4. Transceive AUTH1 APDU

**Reader Signature Input Construction:**
Concatenate Simple TLVs:
- `Tag 0x4D` (Reader Identifier, 8 bytes)
- `Tag 0x86` (`PK.E_eph_X`, 32 bytes)
- `Tag 0x87` (`PK.R_eph_X`, 32 bytes)
- `Tag 0x4C` (Transaction ID, 16 bytes)
- `Tag 0x93` (`readerCtx`, e.g., 0-filled or context bytes)

Sign signature input with **Reader Private Key (`SK.R`)** using SECP256R1 ECDSA (SHA-256) yielding 64-byte `R||S` signature (`sigPoint`).

**AUTH1 Command APDU**:
- `CLA = 0x80`, `INS = 0x81`, `P1 = 0x00`, `P2 = 0x00`
- `Data` = Simple TLV `Tag 0x9E` containing `sigPoint` (64 bytes).

#### 5. Decrypt AUTH1 Response (Smart Card Bridge - SCB Channel)

The AUTH1 response payload is encrypted with SCB mode:

1. **Input Vector Computation (`ICV`)**:
   $$\text{Input Data} = \text{Response\_PCB (15 Bytes)} \,\|\, \text{Counter (1 Byte)}$$
   $$\text{ICV} = \text{AES-128-CBC-Encrypt}(\text{Key} = \text{K.enc}, \text{IV} = 0^{16}, \text{Data} = \text{Input Data})$$
2. **CMAC Response Verification**:
   $$\text{Calculated RMAC} = \text{AES-128-CMAC}(\text{Key} = \text{K.rmac}, \text{Data} = \text{MAC\_Chaining\_Value} \,\|\, \text{Ciphertext})$$
   - Compare `Calculated RMAC[0..7]` with the 8-byte trailing MAC of the response.
3. **AES-CBC Decryption**:
   $$\text{Padded Plaintext} = \text{AES-128-CBC-Decrypt}(\text{Key} = \text{K.enc}, \text{IV} = \text{ICV}, \text{Data} = \text{Ciphertext})$$
   - Remove ISO/IEC 7816-4 padding (`0x80` followed by `0x00`s).

#### 6. Verify Device ECDSA Signature

The decrypted payload contains:
- `Tag 0x4E`: Device Identifier (`Endpoint.ID`, 6 bytes).
- `Tag 0x9E`: Device ECDSA Signature `R||S` (64 bytes).

**Device Verification Input Construction:**
Concatenate Simple TLVs: `Tag 0x4D` (Reader ID) \|\| `Tag 0x86` (`PK.E_eph_X`) \|\| `Tag 0x87` (`PK.R_eph_X`) \|\| `Tag 0x4C` (Tx ID) \|\| `Tag 0x93` (`deviceCtx`).

1. Hash verification input using SHA-256.
2. Verify signature `R||S` against the hash using the stored **Device Endpoint Public Key (`PK.Endpoint`)**.
3. **If verified**:
   - Update stored `persistent_key` for this endpoint in NVS.
   - Send Control Flow Success APDU: `80 3C 01 00`.

---

### Flow Step 5: Attestation Authentication Flow (ISO 18013 / Initial Device Registration)

If during Standard Auth the Endpoint ID (`Tag 0x4E`) is NOT found in stored credentials:

1. Reader sends Control Flow Attestation APDU: `80 3C 40 A0`.
2. Reader selects ISO 18013 AID: `00 A4 04 00 07 A0 00 00 08 58 01 02 00`.
3. Reader sends **Envelope 1 APDU** (`00 C3 00 01`) containing NDEF engagement message.
4. Compute `attestation_salt`:
   $$\text{attestation\_salt} = \text{SHA-256}(\text{CBOR}(\text{DeviceEngagement}))$$
5. Generate random 32-byte shared secret and initialize ISO 18013 AES-GCM secure context.
6. Reader sends **Envelope 2 APDU** (`00 C3 00 00`) requesting CBOR document `com.apple.HomeKit.1.credential`.
7. Decrypt Envelope 2 response payload to reveal CBOR document structure:
   - Extract `issuerSigned` -> `issuerAuth` COSE_Sign1 structure.
   - Extract `issuerId` (8 bytes). Match against stored `Issuer.ID`s.
   - Extract Mobile Security Object (MSO) payload and parse `deviceKeyInfo` -> `deviceKey` (X and Y coordinates).
   - Verify COSE_Sign1 Ed25519 signature over MSO using stored **Issuer Public Key (`PK.Issuer`)**.
8. **On Verification Success**:
   - Construct new 65-byte `PK.Endpoint = 0x04 || X || Y`.
   - Calculate `Endpoint.ID = SHA-1(PK.Endpoint)[0..5]`.
   - Save newly discovered Endpoint under matching Issuer in NVS.
   - Complete transaction and unlock lock.

---

## 5. Cryptographic Reference & Key Schedule

### Key Hierarchy & Storage Summary

```
                      +-----------------------------+
                      |   Reader Private Key SK.R   | (32-byte SECP256R1, NVS)
                      +--------------+--------------+
                                     |
               +---------------------+---------------------+
               |                                           |
    +----------v----------+                     +----------v----------+
    | Reader Public PK.R  |                     | Group Identifier GID|
    |  (65-byte SECP256R1)|                     |  (8-byte SHA-256)   |
    +---------------------+                     +----------+----------+
                                                           |
                                                    Used in ECP Frame
                                                    
                      +-----------------------------+
                      |   Issuer Public Key PK.Iss  | (32-byte Ed25519, NVS)
                      +--------------+--------------+
                                     |
                      +--------------v--------------+
                      | Endpoint Public Key PK.End  | (65-byte SECP256R1, NVS)
                      +--------------+--------------+
                                     |
                                     v
                        [ Standard Auth ECDH Exchange ]
                                     |
                      +--------------v--------------+
                      |   Derived Key (X9.63 KDF)   | (32 bytes)
                      +--------------+--------------+
                                     |
               +---------------------+---------------------+
               |                                           |
    +----------v----------+                     +----------v----------+
    |   Persistent Key    |                     |    Volatile Key     |
    | (32-byte HKDF-SHA)  |                     | (48-byte HKDF-SHA)  |
    +----------+----------+                     +----------+----------+
               |                                           |
        Saved to NVS for                           +-------+-------+
       Fast Auth Cryptogram                        |       |       |
                                                 K.enc   K.mac   K.rmac
                                                 (16B)   (16B)   (16B)
```

### Derivation Algorithms & Formats

| Algorithm / primitive | Purpose | Spec / Curve |
| :--- | :--- | :--- |
| **SECP256R1 (NIST P-256)** | Reader static & ephemeral keys, Endpoint static & ephemeral keys | ECDH & ECDSA with SHA-256 |
| **Ed25519** | Issuer attestation certificate signature verification | Curve25519 |
| **ANSI X9.63 KDF** | Shared key derivation after ECDH | SHA-256, Shared Info = Transaction ID |
| **HKDF-SHA256** | Key schedule derivation for Persistent, Volatile, & Fast Material | RFC 5869 |
| **AES-128-CBC** | SCB command/response encryption | 16-byte blocks, ICV derived per payload |
| **AES-128-CMAC** | SCB command/response authentication | RFC 4493 |
| **AES-256-GCM** | ISO 18013 Attestation Envelope encryption | NIST SP 800-38D |

---

## 6. Implementation Checklist for Custom Readers

To build a standalone HomeKey reader (e.g. on ESP32, STM32, Nordic nRF, Linux PC, or Raspberry Pi), ensure your codebase implements the following steps:

1. **HAP Protocol Stack**:
   - Implement HAP IP / BLE pairing engine.
   - Implement `NFCAccess` service (`UUID: 00000266-...`).
   - Parse top-level and nested TLV8 structures on write to `NFCAccessControlPoint`.
   - Compute `GID = SHA-256(SK.R)[0..7]` when `SK.R` is written.
   - Compute `Endpoint.ID = SHA-1(PK.Endpoint)[0..5]` when DCR is provisioned.
2. **NFC Hardware & ECP Polling**:
   - Configure NFC IC (PN532, PN7160, ST25R3916, etc.) to transmit 18-byte ECP frames.
   - Implement ISO 14443-4 APDU transceiver (`exchangeApdu`).
3. **APDU Engine**:
   - Select AID `A0000008580101`.
   - Process `AUTH0` (`80 80 ...`) and extract `PK.E_eph`.
   - Execute Fast Auth cryptogram match (`HKDF-SHA256`).
   - Execute Standard Auth fallback:
     - SECP256R1 ECDH.
     - ANSI X9.63 KDF.
     - HKDF persistent & volatile key schedules.
     - SCB AES-128-CBC decryption and AES-128-CMAC verification.
     - SECP256R1 ECDSA signature verification.
   - Execute Attestation Auth fallback for unknown endpoints:
     - ISO 18013 envelope exchange.
     - CBOR parser for Mobile Security Object (MSO).
     - Ed25519 COSE_Sign1 signature verification.
4. **Credential Persistence**:
   - Persist Reader Identity (`SK.R`, `PK.R`, `GID`, `Sub-ID`).
   - Persist Issuers (`Issuer.ID`, `PK.Issuer`).
   - Persist Endpoints (`Endpoint.ID`, `PK.Endpoint`, `persistent_key`).
