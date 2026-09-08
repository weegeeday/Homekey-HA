"""HTTP API View for downloading homekeyc.h C++ header file."""

from __future__ import annotations

import logging
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, URL_DOWNLOAD_HOMEKEYC
from .generator import generate_homekey_header
from .storage import HomeKeyStore

_LOGGER = logging.getLogger(__name__)


HTML_WAITING_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Apple HomeKey - Waiting for Pairing</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #111827; color: #f9fafb; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .card { background: #1f2937; border-radius: 16px; padding: 32px; max-width: 540px; width: 100%; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); border: 1px solid #374151; text-align: center; }
        .icon { font-size: 48px; margin-bottom: 16px; display: inline-block; }
        h1 { font-size: 24px; margin: 0 0 12px 0; color: #ffffff; }
        p { font-size: 15px; color: #9ca3af; line-height: 1.6; margin: 0 0 20px 0; }
        .badge { display: inline-flex; align-items: center; gap: 8px; background: #374151; color: #f3f4f6; padding: 8px 16px; border-radius: 9999px; font-weight: 600; font-size: 14px; margin-bottom: 24px; }
        .badge .dot { width: 10px; height: 10px; border-radius: 50%; background: #f59e0b; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        .steps { text-align: left; background: #111827; border-radius: 12px; padding: 20px; border: 1px solid #374151; margin-bottom: 24px; }
        .steps ol { margin: 0; padding-left: 20px; color: #d1d5db; }
        .steps li { margin-bottom: 10px; font-size: 14px; line-height: 1.5; }
        .steps li:last-child { margin-bottom: 0; }
        .btn { display: inline-block; background: #2563eb; color: white; padding: 12px 24px; border-radius: 8px; font-weight: 600; text-decoration: none; transition: background 0.2s; border: none; cursor: pointer; font-size: 15px; }
        .btn:hover { background: #1d4ed8; }
        .footer { font-size: 12px; color: #6b7280; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">🔑</div>
        <h1>Apple HomeKey Token Extractor</h1>
        <div class="badge">
            <span class="dot"></span> Waiting for Apple Home pairing...
        </div>
        <p>The <code>homekeyc.h</code> header file cannot be generated yet because the Virtual Lock has not been paired with Apple Home.</p>
        <div class="steps">
            <strong>Next Steps to Download:</strong>
            <ol>
                <li>Open the <strong>Apple Home</strong> app on your iPhone.</li>
                <li>Tap <strong>+</strong> &rarr; <strong>Add Accessory</strong>.</li>
                <li>Scan the QR code from Home Assistant or enter your Setup PIN code.</li>
                <li>Complete lock setup. Apple Wallet will automatically issue a HomeKey pass.</li>
            </ol>
        </div>
        <button class="btn" onclick="location.reload()">Check Again Now</button>
        <div class="footer">This page automatically checks every 5 seconds...</div>
    </div>
    <script>
        setTimeout(function() {
            location.reload();
        }, 5000);
    </script>
</body>
</html>
"""


class HomeKeyHeaderView(HomeAssistantView):
    """View to serve the homekeyc.h C++ header file."""

    url = "/api/apple_homekey_bthome/download"
    extra_urls = ["/api/apple_homekey_bthome/homekeyc.h"]
    name = "api:apple_homekey_bthome:download"
    requires_auth = False  # Allow direct browser download on local network

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize HTTP view with HomeAssistant reference."""
        self.hass = hass

    def _get_store(self) -> HomeKeyStore | None:
        """Retrieve active HomeKeyStore from hass data."""
        domain_data = self.hass.data.get(DOMAIN, {})
        for key, val in domain_data.items():
            if isinstance(val, dict) and "store" in val:
                return val["store"]
        return None

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request to serve homekeyc.h header file or HTML waiting status page."""
        _LOGGER.debug("Received request for homekeyc.h download from %s", request.remote)
        
        store = self._get_store()
        if store is None or not store.is_provisioned:
            _LOGGER.info("Download attempted before HomeKey keys provisioned. Serving waiting status page.")
            accept_header = request.headers.get("Accept", "")
            if "application/json" in accept_header or request.query.get("json") == "1":
                return web.json_response(
                    {
                        "error": "not_provisioned",
                        "status": "waiting_for_apple_home_pairing",
                        "instructions": "Pair your Apple Home App to the virtual HomeKit Lock accessory first.",
                    },
                    status=400,
                )
            return web.Response(text=HTML_WAITING_TEMPLATE, content_type="text/html", status=200)

        try:
            cpp_content = generate_homekey_header(store)
            return web.Response(
                body=cpp_content.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": "attachment; filename=homekeyc.h",
                    "Cache-Control": "no-store, no-cache, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
        except ValueError as err:
            _LOGGER.warning("Error generating homekeyc.h: %s", err)
            return web.Response(text=f"Error: {err}", content_type="text/plain", status=500)
