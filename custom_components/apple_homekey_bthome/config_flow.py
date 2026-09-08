"""ConfigFlow for Apple HomeKey Token Extractor integration."""

from __future__ import annotations

import random
import socket
import string
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CATEGORY_DOOR_LOCK,
    CONF_FINISH_COLOR,
    CONF_NAME,
    CONF_PORT,
    CONF_SETUP_CODE,
    CONF_SETUP_ID,
    DEFAULT_FINISH_COLOR,
    DEFAULT_NAME,
    DEFAULT_START_PORT,
    DOMAIN,
    HARDWARE_FINISHES,
)


def generate_random_setup_code() -> str:
    """Generate random 8-digit setup code in XXX-YY-ZZZ format."""
    c1 = random.randint(100, 999)
    c2 = random.randint(10, 99)
    c3 = random.randint(100, 999)
    return f"{c1:03d}-{c2:02d}-{c3:03d}"


def generate_random_setup_id() -> str:
    """Generate random 4-character alphanumeric Setup ID."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(4))


def find_available_port(start_port: int = DEFAULT_START_PORT) -> int:
    """Find an available TCP port for the HomeKit driver."""
    port = start_port
    while port < start_port + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                port += 1
    return start_port


class HomeKeyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Apple HomeKey Token Extractor."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check unique entry
            await self.async_set_unique_id(f"homekey_virtual_lock_{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=user_input.get(CONF_NAME, DEFAULT_NAME),
                data=user_input,
            )

        # Generate default random credentials
        random_pin = generate_random_setup_code()
        random_id = generate_random_setup_id()
        suggested_port = find_available_port()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_SETUP_CODE, default=random_pin): str,
                vol.Required(CONF_SETUP_ID, default=random_id): str,
                vol.Required(CONF_PORT, default=suggested_port): int,
                vol.Required(CONF_FINISH_COLOR, default=DEFAULT_FINISH_COLOR): vol.In(
                    list(HARDWARE_FINISHES.keys())
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "generated_pin": random_pin,
                "generated_id": random_id,
                "generated_port": str(suggested_port),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create options flow handler."""
        return HomeKeyOptionsFlowHandler()


class HomeKeyOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for configuration updates."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        config_entry = getattr(self, "config_entry", None)
        if config_entry is None and hasattr(self, "handler"):
            config_entry = self.hass.config_entries.async_get_entry(self.handler)

        options = config_entry.options if config_entry else {}
        entry_data = config_entry.data if config_entry else {}

        finish_color = options.get(
            CONF_FINISH_COLOR,
            entry_data.get(CONF_FINISH_COLOR, DEFAULT_FINISH_COLOR),
        )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_FINISH_COLOR,
                    default=finish_color,
                ): vol.In(list(HARDWARE_FINISHES.keys())),
            }
        )

        try:
            from homeassistant.helpers.network import get_url
            base_url = get_url(self.hass, prefer_external=False)
        except Exception:
            base_url = ""
        
        from .const import URL_DOWNLOAD_HOMEKEYC
        download_url = f"{base_url}{URL_DOWNLOAD_HOMEKEYC}"

        data = self.hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {}) if config_entry else {}
        store = data.get("store")
        status_text = "Ready to download (Provisioned)" if (store and store.is_provisioned) else "Waiting for Apple Home app pairing"

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            description_placeholders={
                "download_url": download_url,
                "status": status_text,
            },
        )
