"""Config flow: the heating system, its options, and rooms as subentries."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentryData,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .features import (
    FEATURE_LEARNING,
    FEATURE_PRESENCE,
    FEATURE_SUN,
    FEATURE_WINDOWS,
    FEATURES,
    feature_on,
)
from .sun import (
    CONF_SUN_CHECK_DELAY,
    CONF_SUN_COLD_BELOW,
    CONF_SUN_CONDITIONS,
    CONF_SUN_DARK_BELOW,
    CONF_SUN_FORECAST,
    CONF_SUN_HOLD,
    CONF_SUN_LUX,
    CONF_SUN_MILD_ABOVE,
    CONF_SUN_ROOMS,
    CONF_SUN_WINDOW_END,
    CONF_SUN_WINDOW_START,
    DEFAULT_SUN_CHECK_DELAY,
    DEFAULT_SUN_COLD_BELOW,
    DEFAULT_SUN_CONDITIONS,
    DEFAULT_SUN_DARK_BELOW,
    DEFAULT_SUN_HOLD,
    DEFAULT_SUN_MILD_ABOVE,
    DEFAULT_SUN_WINDOW_END,
    DEFAULT_SUN_WINDOW_START,
    SUN_CONDITIONS,
)
from .const import (
    CONF_INITIAL_SCHEDULE,
    CONF_NO_SCHEDULE_TEMP,
    DEFAULT_INITIAL_SCHEDULE,
    DEFAULT_WEEK_CHOICE,
    DEFAULT_NO_SCHEDULE_TEMP,
    SCHEDULING_OFF_CHOICE,
    PRESET_ECO,
    PRESET_WARM,
    AWAY_MODES,
    CONF_AWAY_MODE,
    CONF_BUFFER,
    CONF_DRIVES_SOURCE,
    CONF_CH_SWITCH,
    CONF_ECO_TEMP,
    CONF_EXP_CH_ACTIVE,
    CONF_EXP_COMFORT_WEEKDAY,
    CONF_EXP_COMFORT_WEEKEND,
    CONF_EXP_DHW,
    CONF_EXP_DHW_RATE,
    CONF_EXP_FLAME,
    CONF_EXP_GAS,
    CONF_EXP_GAS_AFTER6,
    CONF_EXP_GAS_BEFORE6,
    CONF_EXP_AUTO_APPLY,
    CONF_EXP_NOTIFY,
    CONF_EXP_INTEGRAL,
    CONF_EXP_KD,
    CONF_EXP_KI,
    CONF_EXP_KP,
    CONF_EXP_OUTDOOR,
    CONF_EXP_PEOPLE,
    CONF_EXP_FLOW_REQUEST,
    CONF_EXP_MAX_CAPACITY,
    CONF_EXP_MEMBER_ID,
    CONF_EXP_MIN_MODULATION,
    CONF_EXP_MIN_POWER,
    CONF_EXP_RETURN,
    CONF_EXP_MAX_CH,
    CONF_EXP_DHW_SETPOINT,
    CONF_EXP_ROOM,
    CONF_EXP_WATER,
    CONF_EXP_WEATHER,
    CONF_EXT_SELECT,
    CONF_EXT_TEMP,
    CONF_HEARTBEAT_MIN,
    CONF_HEAT_SOURCE_ENTITY,
    CONF_HEAT_SOURCE_TYPE,
    CONF_HYSTERESIS,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_OFF_TEMP,
    CONF_PRESENCE,
    CONF_ROOM_NAME,
    CONF_SKIP_UNCHANGED,
    CONF_STEP,
    CONF_TEMP_SENSOR,
    CONF_TRVS,
    CONF_WARM_TEMP,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOWS,
    DEFAULT_AWAY_MODE,
    DEFAULT_BUFFER,
    DEFAULT_DRIVES_SOURCE,
    DEFAULT_COMFORT_WEEKDAY,
    DEFAULT_COMFORT_WEEKEND,
    DEFAULT_ECO_TEMP,
    DEFAULT_HEARTBEAT_MIN,
    DEFAULT_HYSTERESIS,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_NOTIFY,
    DEFAULT_OFF_TEMP,
    DEFAULT_SKIP_UNCHANGED,
    DEFAULT_STEP,
    DEFAULT_WARM_TEMP,
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    DOCS_EXPERIMENTAL_URL,
    DOMAIN,
    EXP_ENTITY_KEYS,
    NOTIFY_MODES,
    HEAT_SOURCE_CLIMATE,
    HEAT_SOURCE_OTGW,
    HEAT_SOURCE_SWITCH,
    HEAT_SOURCE_TYPES,
    SUBENTRY_ROOM,
)

DEFAULT_TITLE = "Heating"


def _temp(minimum: float, maximum: float, step: float = 0.5) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="°C",
        )
    )


def _seconds() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=3600, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="s"
        )
    )


def _entities(domain: str | list[str], multiple: bool = False, **kwargs: Any) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, multiple=multiple, **kwargs)
    )


def heat_source_schema(source_type: str) -> vol.Schema:
    """Entities and tuning that depend on the heat source type."""
    if source_type == HEAT_SOURCE_SWITCH:
        return vol.Schema(
            {
                vol.Required(CONF_HEAT_SOURCE_ENTITY): _entities(["switch", "input_boolean"]),
                vol.Required(CONF_HYSTERESIS, default=DEFAULT_HYSTERESIS): _temp(0.1, 2.0, 0.1),
            }
        )
    source = (
        _entities("climate", integration="opentherm_gw")
        if source_type == HEAT_SOURCE_OTGW
        else _entities("climate")
    )
    return vol.Schema(
        {
            vol.Required(CONF_HEAT_SOURCE_ENTITY): source,
            vol.Optional(CONF_CH_SWITCH): _entities(["switch", "input_boolean"]),
        }
    )


PRESENCE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PRESENCE): _entities(
            ["binary_sensor", "input_boolean", "person", "zone", "group", "device_tracker"]
        ),
        vol.Required(CONF_AWAY_MODE, default=DEFAULT_AWAY_MODE): selector.SelectSelector(
            selector.SelectSelectorConfig(options=AWAY_MODES, translation_key=CONF_AWAY_MODE)
        ),
    }
)

SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_OFF_TEMP, default=DEFAULT_OFF_TEMP): _temp(5, 16),
        vol.Required(CONF_NO_SCHEDULE_TEMP, default=DEFAULT_NO_SCHEDULE_TEMP): _temp(5, 21),
        vol.Required(CONF_SKIP_UNCHANGED, default=DEFAULT_SKIP_UNCHANGED): selector.BooleanSelector(),
        vol.Required(CONF_HEARTBEAT_MIN, default=DEFAULT_HEARTBEAT_MIN): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5, max=240, step=5, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="min"
            )
        ),
    }
)


class CloudlessMultiroomThermostatFlow(ConfigFlow, domain=DOMAIN):
    """Create a heating system."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._room: dict[str, Any] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_ROOM: RoomSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SettingsOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_NAME] = user_input[CONF_NAME]
            self._data[CONF_HEAT_SOURCE_TYPE] = user_input[CONF_HEAT_SOURCE_TYPE]
            return await self.async_step_heat_source()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_TITLE): selector.TextSelector(),
                    vol.Required(CONF_HEAT_SOURCE_TYPE, default=HEAT_SOURCE_CLIMATE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=HEAT_SOURCE_TYPES, translation_key=CONF_HEAT_SOURCE_TYPE
                        )
                    ),
                }
            ),
        )

    async def async_step_heat_source(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_room()
        return self.async_show_form(
            step_id="heat_source",
            data_schema=heat_source_schema(self._data[CONF_HEAT_SOURCE_TYPE]),
        )

    # The first room (#120): setup asks only for the heat source and one room.
    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {**user_input, CONF_ROOM_NAME: user_input[CONF_ROOM_NAME].strip()}
            errors = validate_room(user_input)
            if not user_input[CONF_ROOM_NAME]:
                errors[CONF_ROOM_NAME] = "name_required"
            if not errors:
                user_input[CONF_STEP] = float(user_input[CONF_STEP])
                self._room.update(user_input)
                return await self.async_step_room_sensors()
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(ROOM_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_room_sensors(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._room.update(user_input)
            return await self.async_step_room_schedule()
        return self.async_show_form(
            step_id="room_sensors",
            data_schema=sensors_schema(windows=False),
            description_placeholders={"room": self._room[CONF_ROOM_NAME]},
        )

    async def async_step_room_schedule(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            room = {**self._room, CONF_INITIAL_SCHEDULE: user_input[CONF_INITIAL_SCHEDULE]}
            title = self._data.pop(CONF_NAME)
            return self.async_create_entry(
                title=title,
                data=self._data,
                subentries=[
                    ConfigSubentryData(
                        data=room, subentry_type=SUBENTRY_ROOM, title=room[CONF_ROOM_NAME], unique_id=None
                    )
                ],
            )
        return self.async_show_form(
            step_id="room_schedule",
            data_schema=initial_schedule_schema(),
            description_placeholders={"room": self._room[CONF_ROOM_NAME]},
        )


def initial_schedule_schema() -> vol.Schema:
    """The default week, or scheduling off (#115, 2.0.1)."""
    options = [DEFAULT_WEEK_CHOICE, SCHEDULING_OFF_CHOICE]
    return vol.Schema(
        {
            vol.Required(CONF_INITIAL_SCHEDULE, default=DEFAULT_INITIAL_SCHEDULE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options, translation_key=CONF_INITIAL_SCHEDULE,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


def experimental_schema(rooms: dict[str, str]) -> vol.Schema:
    """Entities for the experimental features; everything optional."""
    room_options = [selector.SelectOptionDict(value=k, label=v) for k, v in rooms.items()]
    fields: dict[Any, Any] = {}
    if room_options:
        fields[vol.Required(CONF_EXP_ROOM, default=room_options[0]["value"])] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=room_options, mode=selector.SelectSelectorMode.DROPDOWN)
        )
    fields.update(
        {
            vol.Required(CONF_EXP_COMFORT_WEEKDAY, default=DEFAULT_COMFORT_WEEKDAY): selector.TimeSelector(),
            vol.Required(CONF_EXP_COMFORT_WEEKEND, default=DEFAULT_COMFORT_WEEKEND): selector.TimeSelector(),
            vol.Optional(CONF_EXP_OUTDOOR): _entities("sensor", device_class="temperature"),
            vol.Optional(CONF_EXP_WEATHER): _entities("weather"),
            vol.Optional(CONF_EXP_PEOPLE): _entities(["zone", "sensor"]),
            vol.Optional(CONF_EXP_GAS): _entities("sensor"),
            vol.Optional(CONF_EXP_FLAME): _entities("binary_sensor"),
            vol.Optional(CONF_EXP_DHW): _entities("binary_sensor"),
            vol.Optional(CONF_EXP_CH_ACTIVE): _entities("binary_sensor"),
            vol.Optional(CONF_EXP_DHW_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.001, max=0.1, step=0.001, mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="m³/min",
                )
            ),
            vol.Optional(CONF_EXP_WATER): _entities("sensor"),
            vol.Optional(CONF_EXP_RETURN): _entities("sensor"),
            vol.Optional(CONF_EXP_MAX_CH): _entities(["sensor", "number", "input_number"]),
            vol.Optional(CONF_EXP_FLOW_REQUEST): _entities("sensor"),
            vol.Optional(CONF_EXP_MEMBER_ID): _entities("sensor"),
            vol.Optional(CONF_EXP_MAX_CAPACITY): _entities("sensor"),
            vol.Optional(CONF_EXP_MIN_MODULATION): _entities("sensor"),
            vol.Optional(CONF_EXP_MIN_POWER): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=40, step=0.1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="kW",
                )
            ),
            vol.Optional(CONF_EXP_DHW_SETPOINT): _entities("sensor"),
            vol.Optional(CONF_EXP_KP): _entities(["number", "input_number"]),
            vol.Optional(CONF_EXP_KI): _entities(["number", "input_number"]),
            vol.Optional(CONF_EXP_KD): _entities(["number", "input_number"]),
            vol.Optional(CONF_EXP_INTEGRAL): _entities("sensor"),
            vol.Required(CONF_EXP_AUTO_APPLY, default=False): selector.BooleanSelector(),
            vol.Required(CONF_EXP_NOTIFY, default=DEFAULT_NOTIFY): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=NOTIFY_MODES, translation_key=CONF_EXP_NOTIFY,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_EXP_GAS_BEFORE6): _entities("sensor"),
            vol.Optional(CONF_EXP_GAS_AFTER6): _entities("sensor"),
        }
    )
    return vol.Schema(fields)


class SettingsOptionsFlow(OptionsFlow):
    """A menu: system settings, Features, and a page per feature that is on and has settings (#120)."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._pages: list[str] = []

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options, **self._options}

    def _on(self, key: str) -> bool:
        rooms = [sub.data for sub in self.config_entry.subentries.values() if sub.subentry_type == SUBENTRY_ROOM]
        return feature_on(self._current, rooms, key)

    async def _save(self, changes: dict[str, Any]) -> ConfigFlowResult:
        self._options.update(changes)
        if self._pages:
            return await getattr(self, f"async_step_{self._pages.pop(0)}")()
        return self.async_create_entry(data={**self.config_entry.options, **self._options})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["settings", "features"]
        if self._on(FEATURE_PRESENCE):
            menu.append("presence")
        if self._on(FEATURE_SUN):
            menu.append("sun_assist")
        if self._on(FEATURE_LEARNING):
            menu.append("experimental")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = self._current
        schema = vol.Schema(
            {**heat_source_schema(current[CONF_HEAT_SOURCE_TYPE]).schema, **SETTINGS_SCHEMA.schema}
        )
        if user_input is not None:
            changes = dict(user_input)
            if any(str(key) == CONF_CH_SWITCH for key in schema.schema):
                changes.setdefault(CONF_CH_SWITCH, None)  # cleared really clears
            return await self._save(changes)
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                schema, {k: v for k, v in current.items() if v is not None}
            ),
        )

    async def async_step_features(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            was = {key: self._on(key) for key in FEATURES}
            changes = {key: bool(user_input[key]) for key in FEATURES}
            # A feature switched on that needs settings opens its page next
            if changes[FEATURE_PRESENCE] and (not was[FEATURE_PRESENCE] or not self._current.get(CONF_PRESENCE)):
                self._pages.append("presence")
            if changes[FEATURE_SUN] and (not was[FEATURE_SUN] or not self._current.get(CONF_SUN_FORECAST)):
                self._pages.append("sun_assist")
            if changes[FEATURE_LEARNING] and not was[FEATURE_LEARNING]:
                self._pages.append("experimental")
            return await self._save(changes)
        schema = vol.Schema({vol.Required(key): selector.BooleanSelector() for key in FEATURES})
        return self.async_show_form(
            step_id="features",
            data_schema=self.add_suggested_values_to_schema(schema, {key: self._on(key) for key in FEATURES}),
            description_placeholders={"docs_url": DOCS_EXPERIMENTAL_URL},
        )

    async def async_step_sun_assist(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sun assist settings live here, never in the card (decided 2026-11-07)."""
        if user_input is not None:
            changes = dict(user_input)
            changes.setdefault(CONF_SUN_LUX, None)  # cleared really clears
            changes.setdefault(CONF_SUN_MILD_ABOVE, None)
            changes[CONF_SUN_CHECK_DELAY] = int(changes[CONF_SUN_CHECK_DELAY])
            return await self._save(changes)
        rooms = [
            selector.SelectOptionDict(value=sub.subentry_id, label=sub.title)
            for sub in self.config_entry.subentries.values()
            if sub.subentry_type == SUBENTRY_ROOM
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_SUN_FORECAST): _entities("weather"),
                vol.Required(CONF_SUN_CONDITIONS, default=DEFAULT_SUN_CONDITIONS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=SUN_CONDITIONS, multiple=True, translation_key=CONF_SUN_CONDITIONS
                    )
                ),
                vol.Required(CONF_SUN_ROOMS, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=rooms, multiple=True)
                ),
                vol.Optional(CONF_SUN_MILD_ABOVE): _temp(-10, 30),
                vol.Required(CONF_SUN_HOLD, default=DEFAULT_SUN_HOLD): _temp(5, 21),
                vol.Required(CONF_SUN_WINDOW_START, default=DEFAULT_SUN_WINDOW_START): selector.TimeSelector(),
                vol.Required(CONF_SUN_WINDOW_END, default=DEFAULT_SUN_WINDOW_END): selector.TimeSelector(),
                vol.Required(CONF_SUN_COLD_BELOW, default=DEFAULT_SUN_COLD_BELOW): _temp(5, 25),
                vol.Optional(CONF_SUN_LUX): _entities("sensor", device_class="illuminance"),
                vol.Required(CONF_SUN_DARK_BELOW, default=DEFAULT_SUN_DARK_BELOW): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100000, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="lx"
                    )
                ),
                vol.Required(CONF_SUN_CHECK_DELAY, default=DEFAULT_SUN_CHECK_DELAY): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=15, max=420, step=15, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="min"
                    )
                ),
            }
        )
        current = self._current
        if CONF_SUN_MILD_ABOVE not in current:  # first time: suggest the default, can be cleared
            current = {**current, CONF_SUN_MILD_ABOVE: DEFAULT_SUN_MILD_ABOVE}
        return self.async_show_form(
            step_id="sun_assist",
            data_schema=self.add_suggested_values_to_schema(
                schema, {k: v for k, v in current.items() if v is not None}
            ),
        )

    async def async_step_presence(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._save(dict(user_input))
        current = self._current
        return self.async_show_form(
            step_id="presence",
            data_schema=self.add_suggested_values_to_schema(
                PRESENCE_SCHEMA, {k: v for k, v in current.items() if v is not None}
            ),
        )

    async def async_step_experimental(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        rooms = {
            sub.subentry_id: sub.title
            for sub in self.config_entry.subentries.values()
            if sub.subentry_type == SUBENTRY_ROOM
        }
        if user_input is not None:
            data = dict(user_input)
            for key in (*EXP_ENTITY_KEYS, CONF_EXP_DHW_RATE):  # cleared fields really clear
                if not user_input.get(key):
                    data[key] = None
            return await self._save(data)
        current = self._current
        suggested = {k: v for k, v in current.items() if v is not None}
        if CONF_EXP_PEOPLE not in current and self.hass.states.get("zone.home"):
            suggested[CONF_EXP_PEOPLE] = "zone.home"
        if suggested.get(CONF_EXP_ROOM) not in rooms:
            suggested.pop(CONF_EXP_ROOM, None)
        return self.async_show_form(
            step_id="experimental",
            data_schema=self.add_suggested_values_to_schema(experimental_schema(rooms), suggested),
            description_placeholders={"docs_url": DOCS_EXPERIMENTAL_URL},
        )


# Step 1: name and temperature settings
ROOM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ROOM_NAME): selector.TextSelector(),
        vol.Required(CONF_ECO_TEMP, default=DEFAULT_ECO_TEMP): _temp(5, 30),
        vol.Required(CONF_WARM_TEMP, default=DEFAULT_WARM_TEMP): _temp(5, 30),
        vol.Required(CONF_BUFFER, default=DEFAULT_BUFFER): _temp(0, 3, 0.1),
        vol.Required(CONF_DRIVES_SOURCE, default=DEFAULT_DRIVES_SOURCE): selector.BooleanSelector(),
        vol.Required(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): _temp(5, 30),
        vol.Required(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): _temp(5, 35),
        vol.Required(CONF_STEP, default=str(DEFAULT_STEP)): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["0.1", "0.5", "1.0"])
        ),
    }
)

# Step 2: sensors and valves; window fields only with the Windows feature on (#120)
def sensors_schema(windows: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_TEMP_SENSOR): _entities("sensor", device_class="temperature"),
        vol.Optional(CONF_TRVS, default=[]): _entities("climate", multiple=True),
        vol.Optional(CONF_EXT_TEMP, default=[]): _entities("number", multiple=True),
        vol.Optional(CONF_EXT_SELECT, default=[]): _entities("select", multiple=True),
    }
    if windows:
        fields.update(
            {
                vol.Optional(CONF_WINDOWS, default=[]): _entities(
                    ["binary_sensor", "input_boolean"], multiple=True
                ),
                vol.Required(CONF_WINDOW_OPEN_DELAY, default=DEFAULT_WINDOW_OPEN_DELAY): _seconds(),
                vol.Required(CONF_WINDOW_CLOSE_DELAY, default=DEFAULT_WINDOW_CLOSE_DELAY): _seconds(),
            }
        )
    return vol.Schema(fields)


def validate_room(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    low, high = float(data[CONF_MIN_TEMP]), float(data[CONF_MAX_TEMP])
    if low >= high:
        errors[CONF_MAX_TEMP] = "max_below_min"
    for key in (CONF_ECO_TEMP, CONF_WARM_TEMP):
        if not low <= float(data[key]) <= high:
            errors[key] = "preset_out_of_range"
    return errors


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or edit a room in two steps: room and temperatures, then sensors."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._editing = False

    @property
    def _current(self) -> dict[str, Any]:
        """Stored room data when editing, else empty.

        Eco and Warm live in the schedule file (#112); the form shows them from
        there and hands edits back through the room, which moves them on load.
        """
        if not self._editing:
            return {}
        sub = self._get_reconfigure_subentry()
        current = dict(sub.data)
        entry = self._get_entry()
        controller = getattr(entry, "runtime_data", None)
        store = getattr(controller, "schedules", None)
        temps = store.temperatures(sub.subentry_id) if store is not None else None
        for preset, key in ((PRESET_ECO, CONF_ECO_TEMP), (PRESET_WARM, CONF_WARM_TEMP)):
            if temps and temps.get(preset) is not None:
                current[key] = temps[preset]
        return current

    def _windows_on(self) -> bool:
        entry = self._get_entry()
        rooms = [sub.data for sub in entry.subentries.values() if sub.subentry_type == SUBENTRY_ROOM]
        return feature_on({**entry.data, **entry.options}, rooms, FEATURE_WINDOWS)

    def _name_taken(self, name: str) -> bool:
        own_id = self._get_reconfigure_subentry().subentry_id if self._editing else None
        return any(
            sub.subentry_type == SUBENTRY_ROOM
            and sub.subentry_id != own_id
            and sub.title.casefold() == name.casefold()
            for sub in self._get_entry().subentries.values()
        )

    # Step 1 -----------------------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._room_step("user", user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._editing = True
        return await self._room_step("reconfigure", user_input)

    async def _room_step(self, step_id: str, user_input: dict[str, Any] | None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {**user_input, CONF_ROOM_NAME: user_input[CONF_ROOM_NAME].strip()}
            errors = validate_room(user_input)
            if not user_input[CONF_ROOM_NAME]:
                errors[CONF_ROOM_NAME] = "name_required"
            elif self._name_taken(user_input[CONF_ROOM_NAME]):
                errors[CONF_ROOM_NAME] = "name_exists"
            if not errors:
                user_input[CONF_STEP] = float(user_input[CONF_STEP])
                self._data.update(user_input)
                return await self.async_step_sensors()
        values = user_input if user_input is not None else self._current
        if values:
            values = {**values, CONF_STEP: str(values.get(CONF_STEP, DEFAULT_STEP))}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(ROOM_SCHEMA, values),
            errors=errors,
        )

    # Step 3 (Add room only) ---------------------------------------------------
    async def async_step_schedule(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """A new room never starts without a schedule: the default week, or scheduling off (#115)."""
        if user_input is not None:
            data = {**self._data, CONF_INITIAL_SCHEDULE: user_input[CONF_INITIAL_SCHEDULE]}
            return self.async_create_entry(title=data[CONF_ROOM_NAME], data=data)
        return self.async_show_form(
            step_id="schedule",
            data_schema=initial_schedule_schema(),
            description_placeholders={"room": self._data[CONF_ROOM_NAME]},
        )

    # Step 2 -----------------------------------------------------------------
    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            # "area" was stored by an earlier version; drop it on edit. Fields
            # of a feature that is off (windows) aren't in the form: keep them.
            kept = dict(self._get_reconfigure_subentry().data) if self._editing else {}
            data = {**kept, **{k: v for k, v in self._data.items() if k != "area"}, **user_input}
            data.pop("area", None)
            title = data[CONF_ROOM_NAME]
            if self._editing:
                return self.async_update_and_abort(
                    self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data
                )
            self._data = data
            return await self.async_step_schedule()
        return self.async_show_form(
            step_id="sensors",
            data_schema=self.add_suggested_values_to_schema(sensors_schema(self._windows_on()), self._current),
            description_placeholders={"room": self._data[CONF_ROOM_NAME]},
        )
