"""HTTP API View for downloading homekeyc.h C++ header file."""

from __future__ import annotations

import logging
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import URL_DOWNLOAD_HOMEKEYC
from .generator import generate_homekey_header
from .storage import HomeKeyStore

_LOGGER = logging.getLogger(__name__)


class HomeKeyHeaderView(HomeAssistantView):
    """View to serve the homekeyc.h C++ header file."""

    url = URL_DOWNLOAD_HOMEKEYC
    name = "api:apple_homekey_bthome:download"
    requires_auth = False  # Allow direct download on local network

    def __init__(self, store: HomeKeyStore) -> None:
        """Initialize HTTP view with HomeKey store reference."""
        self.store = store

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request to serve homekeyc.h header file."""
        _LOGGER.debug("Received request for homekeyc.h download from %s", request.remote)
        
        try:
            cpp_content = generate_homekey_header(self.store)
            return web.Response(
                body=cpp_content.encode("utf-8"),
                content_type="text/x-chdr",
                headers={
                    "Content-Disposition": "attachment; filename=homekeyc.h",
                    "Cache-Control": "no-store, no-cache, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
        except ValueError as err:
            _LOGGER.warning("Download attempted before HomeKey keys provisioned: %s", err)
            return web.json_response(
                {
                    "error": "not_provisioned",
                    "message": str(err),
                    "pairing_status": "Waiting for Apple Home App pairing...",
                    "instructions": "Pair your Apple Home App to the virtual HomeKit Lock accessory first. Once paired, Apple will provision the HomeKey keys down to Home Assistant, enabling this download endpoint.",
                },
                status=400,
            )
