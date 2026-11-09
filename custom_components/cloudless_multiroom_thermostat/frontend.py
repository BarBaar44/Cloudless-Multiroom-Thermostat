"""Serve the bundled Heating Control Card and register it as a dashboard resource.

The card lives in ``www/`` next to this file. It is served from the
integration's own static path and added to the dashboard resources (storage
mode, the default), with the integration version in the URL so browsers load
the new card after an update. Dashboards in YAML mode need the resource added
by hand; the log says which URL.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_BASE = f"/{DOMAIN}"
CARD_FILE = "heating-control-card.js"
CARD_URL = f"{URL_BASE}/{CARD_FILE}"
WWW = Path(__file__).parent / "www"


def _lovelace(hass: HomeAssistant):
    """Return the Lovelace data, or None when dashboards are not loaded."""
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415
    except ImportError:
        return None
    return hass.data.get(LOVELACE_DATA)


async def _async_resources(hass: HomeAssistant):
    """Return the storage-mode resource collection, loaded, or None."""
    from homeassistant.components.lovelace.const import MODE_STORAGE  # noqa: PLC0415

    data = _lovelace(hass)
    if data is None:
        return None
    if data.resource_mode != MODE_STORAGE:
        return None
    resources = data.resources
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    return resources


def _is_card(url: str) -> bool:
    return url.split("?", 1)[0].rstrip("/").endswith(f"/{CARD_FILE}")


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Serve the card and make sure the dashboards load it. Never raises."""
    try:
        await _async_setup_frontend(hass)
    except Exception:  # noqa: BLE001  # the card must never block the heating
        _LOGGER.exception("Could not set up the Heating Control Card; the heating itself is not affected")


async def _async_setup_frontend(hass: HomeAssistant) -> None:
    if getattr(hass, "http", None) is None:
        return
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    await hass.http.async_register_static_paths([StaticPathConfig(URL_BASE, str(WWW), cache_headers=True)])
    version = (await async_get_integration(hass, DOMAIN)).version
    url = f"{CARD_URL}?v={version}"

    data = _lovelace(hass)
    if data is None:
        return
    resources = await _async_resources(hass)
    if resources is None:
        _LOGGER.info(
            "Dashboards use YAML mode: add the Heating Control Card yourself as a resource, "
            "url %s, type module",
            url,
        )
        return

    ours = None
    for item in resources.async_items():
        item_url = item.get("url", "")
        if not _is_card(item_url):
            continue
        if item_url.split("?", 1)[0] == CARD_URL:
            ours = item
        else:
            _LOGGER.warning(
                "A separately installed Heating Control Card is also loaded (%s). The card now ships with "
                "Cloudless Multiroom Thermostat: remove the old card in HACS or the Marketplace and its "
                "dashboard resource, so only one copy loads",
                item_url,
            )
    if ours is None:
        await resources.async_create_item({"res_type": "module", "url": url})
    elif ours.get("url") != url:
        await resources.async_update_item(ours["id"], {"res_type": "module", "url": url})


async def async_remove_frontend(hass: HomeAssistant) -> None:
    """Remove the card's dashboard resource (the last heating system was removed)."""
    try:
        resources = await _async_resources(hass)
        if resources is None:
            return
        for item in list(resources.async_items()):
            if item.get("url", "").split("?", 1)[0] == CARD_URL:
                await resources.async_delete_item(item["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not remove the Heating Control Card resource")
