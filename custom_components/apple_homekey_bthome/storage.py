"""Persistent storage manager for Apple HomeKey cryptographic credentials."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


def derive_reader_public_key(sk_r_bytes: bytes) -> tuple[bytes, bytes]:
    """Derive 65-byte uncompressed public key (0x04 || X || Y) and 32-byte X-coord from 32-byte SECP256R1 private key."""
    priv_num = int.from_bytes(sk_r_bytes, "big")
    priv_key = ec.derive_private_key(priv_num, ec.SECP256R1())
    pub_numbers = priv_key.public_key().public_numbers()
    
    x_bytes = pub_numbers.x.to_bytes(32, "big")
    y_bytes = pub_numbers.y.to_bytes(32, "big")
    pk_r = b"\x04" + x_bytes + y_bytes
    return pk_r, x_bytes


def derive_gid(sk_r_bytes: bytes) -> bytes:
    """Compute 8-byte Group Identifier GID = SHA-256(SK.R)[0..7]."""
    return hashlib.sha256(sk_r_bytes).digest()[:8]


def derive_endpoint_id(pk_endpoint_bytes: bytes) -> bytes:
    """Compute 6-byte Endpoint Identifier Endpoint.ID = SHA-1(PK.Endpoint)[0..5]."""
    return hashlib.sha1(pk_endpoint_bytes).digest()[:6]


class HomeKeyStore:
    """Async store for HomeKey keys and HomeKit accessory state."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize key store."""
        self.hass = hass
        self.entry_id = entry_id
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")
        
        self.sk_r: bytes | None = None
        self.pk_r: bytes | None = None
        self.pk_r_x: bytes | None = None
        self.gid: bytes | None = None
        self.sub_id: bytes | None = None
        
        self.issuers: dict[str, dict[str, Any]] = {}
        self.endpoints: list[dict[str, Any]] = []
        
        self.configuration_state: int = 1

    @property
    def is_provisioned(self) -> bool:
        """Return True if Reader Private Key (SK.R) has been provisioned."""
        return self.sk_r is not None

    async def async_load(self) -> None:
        """Load data from persistent storage."""
        data = await self._store.async_load()
        if not data:
            _LOGGER.debug("No existing HomeKey store found, starting fresh")
            return

        self.configuration_state = data.get("configuration_state", 1)
        
        sk_r_hex = data.get("sk_r")
        if sk_r_hex:
            self.sk_r = bytes.fromhex(sk_r_hex)
            self.pk_r, self.pk_r_x = derive_reader_public_key(self.sk_r)
            self.gid = derive_gid(self.sk_r)

        sub_id_hex = data.get("sub_id")
        if sub_id_hex:
            self.sub_id = bytes.fromhex(sub_id_hex)

        self.issuers = data.get("issuers", {})
        self.endpoints = data.get("endpoints", [])
        
        _LOGGER.info(
            "Loaded HomeKey store: SK.R provisioned=%s, GID=%s, Endpoints=%d",
            self.sk_r is not None,
            self.gid.hex() if self.gid else "None",
            len(self.endpoints),
        )

    async def async_save(self) -> None:
        """Save current state to persistent storage."""
        data = {
            "configuration_state": self.configuration_state,
            "sk_r": self.sk_r.hex() if self.sk_r else None,
            "sub_id": self.sub_id.hex() if self.sub_id else None,
            "issuers": self.issuers,
            "endpoints": self.endpoints,
        }
        await self._store.async_save(data)

    def set_reader_key(self, sk_r: bytes, sub_id: bytes) -> None:
        """Set or update Reader Private Key (SK.R) and Sub-ID."""
        self.sk_r = sk_r
        self.sub_id = sub_id
        self.pk_r, self.pk_r_x = derive_reader_public_key(sk_r)
        self.gid = derive_gid(sk_r)
        self.configuration_state += 1
        _LOGGER.info("Provisioned new Reader Private Key! GID=%s", self.gid.hex())

    def ensure_reader_key(self) -> None:
        """Ensure a Reader Private Key (SK.R) exists, generating a new SECP256R1 key if unprovisioned."""
        if self.sk_r is None:
            import os
            sk_r = os.urandom(32)
            sub_id = os.urandom(8)
            self.set_reader_key(sk_r, sub_id)
            _LOGGER.info("Auto-generated initial Reader Private Key (SK.R). GID=%s", self.gid.hex())

    def remove_reader_key(self) -> None:
        """Remove provisioned Reader Private Key."""
        self.sk_r = None
        self.pk_r = None
        self.pk_r_x = None
        self.gid = None
        self.sub_id = None
        self.configuration_state += 1
        _LOGGER.info("Removed Reader Private Key")

    def add_endpoint(self, issuer_id: bytes, raw_pub_key_64: bytes) -> dict[str, Any]:
        """Provision a new Endpoint key (64-byte raw X||Y)."""
        pk_endpoint = b"\x04" + raw_pub_key_64
        pk_endpoint_x = raw_pub_key_64[:32]
        endpoint_id = derive_endpoint_id(pk_endpoint)

        issuer_id_hex = issuer_id.hex()
        endpoint_id_hex = endpoint_id.hex()

        if issuer_id_hex not in self.issuers:
            self.issuers[issuer_id_hex] = {
                "issuer_id": issuer_id_hex,
            }

        # Check if already exists
        for ep in self.endpoints:
            if ep["endpoint_id"] == endpoint_id_hex:
                _LOGGER.info("Endpoint %s already provisioned under issuer %s", endpoint_id_hex, issuer_id_hex)
                return ep

        record = {
            "issuer_id": issuer_id_hex,
            "endpoint_id": endpoint_id_hex,
            "public_key": pk_endpoint.hex(),
            "public_key_x": pk_endpoint_x.hex(),
        }
        self.endpoints.append(record)
        self.configuration_state += 1
        _LOGGER.info("Provisioned Endpoint %s under Issuer %s", endpoint_id_hex, issuer_id_hex)
        return record

    def remove_endpoint(self, issuer_id: bytes, endpoint_id: bytes | None = None) -> None:
        """Remove endpoint credential(s)."""
        issuer_hex = issuer_id.hex()
        if endpoint_id:
            ep_hex = endpoint_id.hex()
            self.endpoints = [e for e in self.endpoints if not (e["issuer_id"] == issuer_hex and e["endpoint_id"] == ep_hex)]
        else:
            self.endpoints = [e for e in self.endpoints if e["issuer_id"] != issuer_hex]
            if issuer_hex in self.issuers:
                del self.issuers[issuer_hex]
        self.configuration_state += 1
        _LOGGER.info("Removed endpoint credential(s) for issuer %s", issuer_hex)
