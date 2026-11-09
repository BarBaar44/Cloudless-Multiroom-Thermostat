"""The bundled Heating Control Card: static path and dashboard resource."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component

from custom_components.cloudless_multiroom_thermostat import frontend
from custom_components.cloudless_multiroom_thermostat.const import DOMAIN


@pytest.fixture
async def resources(hass: HomeAssistant):
    """Dashboards in storage mode (the default) and a stand-in web server."""
    assert await async_setup_component(hass, "lovelace", {})
    hass.http = MagicMock()  # after lovelace, which sets up the real http
    hass.http.async_register_static_paths = AsyncMock()
    res = hass.data[LOVELACE_DATA].resources
    await res.async_get_info()  # load the collection
    return res


async def _url(hass: HomeAssistant) -> str:
    version = (await async_get_integration(hass, DOMAIN)).version
    return f"/{DOMAIN}/heating-control-card.js?v={version}"


def _urls(res) -> list[str]:
    return [item["url"] for item in res.async_items()]


async def test_card_file_ships_with_the_integration() -> None:
    assert (frontend.WWW / frontend.CARD_FILE).is_file()


async def test_serves_the_card_and_adds_the_resource(hass: HomeAssistant, resources) -> None:
    await frontend.async_setup_frontend(hass)
    hass.http.async_register_static_paths.assert_awaited_once()
    (cfg,) = hass.http.async_register_static_paths.await_args.args[0]
    assert cfg.url_path == f"/{DOMAIN}"
    assert cfg.path == str(frontend.WWW)
    assert _urls(resources) == [await _url(hass)]
    assert resources.async_items()[0]["type"] == "module"

    # A restart adds nothing.
    await frontend.async_setup_frontend(hass)
    assert _urls(resources) == [await _url(hass)]


async def test_update_changes_the_version_in_place(hass: HomeAssistant, resources) -> None:
    await resources.async_create_item({"res_type": "module", "url": f"/{DOMAIN}/heating-control-card.js?v=0.0.1"})
    await resources.async_create_item({"res_type": "module", "url": "/local/other-card.js"})
    await frontend.async_setup_frontend(hass)
    assert sorted(_urls(resources)) == sorted(["/local/other-card.js", await _url(hass)])


async def test_old_separate_card_is_reported_not_removed(hass: HomeAssistant, resources, caplog) -> None:
    old = "/hacsfiles/Heating-Control-Card/heating-control-card.js?hacstag=123"
    await resources.async_create_item({"res_type": "module", "url": old})
    await frontend.async_setup_frontend(hass)
    assert old in _urls(resources)
    assert await _url(hass) in _urls(resources)
    assert "separately installed Heating Control Card" in caplog.text


async def test_yaml_mode_only_logs(hass: HomeAssistant, caplog) -> None:
    assert await async_setup_component(hass, "lovelace", {"lovelace": {"resource_mode": "yaml"}})
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    await frontend.async_setup_frontend(hass)
    hass.http.async_register_static_paths.assert_awaited_once()
    assert "add the Heating Control Card yourself" in caplog.text


async def test_without_web_server_or_dashboards_nothing_happens(hass: HomeAssistant) -> None:
    hass.http = None
    await frontend.async_setup_frontend(hass)  # no error
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    await frontend.async_setup_frontend(hass)  # lovelace not loaded: served, nothing registered
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_errors_never_raise(hass: HomeAssistant, caplog) -> None:
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock(side_effect=RuntimeError("boom"))
    await frontend.async_setup_frontend(hass)
    assert "heating itself is not affected" in caplog.text


async def test_remove_drops_only_our_resource(hass: HomeAssistant, resources) -> None:
    await resources.async_create_item({"res_type": "module", "url": "/local/other-card.js"})
    await frontend.async_setup_frontend(hass)
    await frontend.async_remove_frontend(hass)
    assert _urls(resources) == ["/local/other-card.js"]


async def test_card_is_served_over_http(hass: HomeAssistant, hass_client) -> None:
    """End to end: the real web server returns the bundled file."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "lovelace", {})
    await frontend.async_setup_frontend(hass)
    client = await hass_client()
    resp = await client.get(await _url(hass))
    assert resp.status == 200
    assert "javascript" in resp.headers["Content-Type"]
    assert await resp.text() == (frontend.WWW / frontend.CARD_FILE).read_text()
