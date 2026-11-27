#!/usr/bin/env python3
"""Create a Cloudless Multiroom Thermostat entry with all heating_sim rooms.

Runs the real config flow and room flows through Home Assistant's REST API,
so it also tests the forms. Standard library only.

  python3 setup_heating.py --token <long-lived token>
  python3 setup_heating.py --token <token> --source switch   # relay boiler
  python3 setup_heating.py --token <token> --url http://host:8124

On a fresh Home Assistant (onboarding not done yet) it can do onboarding
first, creating the owner account, and then use that login:

  python3 setup_heating.py --onboard --username test --password testtest
  python3 setup_heating.py --onboard --wait 900 ...   # wait for HA to come up

Learning features, with every field on their page pointed at a sim entity:

  python3 setup_heating.py --token <token> --learning               # observe only
  python3 setup_heating.py --token <token> --learning --auto-apply  # also apply PID advice
  python3 setup_heating.py --token <token> --learning --notify full # evening notification

They time warm-ups in real minutes, so --learning sets the sim to real time
(number.sim_speed 1) unless --speed says otherwise.

v2: setup asks for the heat source and the first room only; the script then
switches on the features (presence and away, windows, sun assist, guest
mode; learning with --learning), adds the other rooms, a Sleep preset and a
week schedule per room. The upgrade path from v1 (rooms without a schedule
hold 15 °C, Repairs lists them) is in the README.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DOMAIN = "cloudless_multiroom_thermostat"

# Must match heating_sim in config/configuration.yaml. The first room is added
# in setup, before the Windows feature is on, so it is one without a window.
ROOMS = [
    {"name": "Office", "trvs": 1, "window": None, "warm": 19.5},
    {"name": "Living Room", "trvs": 3, "window": "input_boolean.sim_living_room_garden_door", "warm": 19.0},
    {"name": "Sports Room", "trvs": 1, "window": None, "warm": 16.0},
    {"name": "Master Bedroom", "trvs": 2, "window": "input_boolean.sim_master_bedroom_window", "warm": 17.0},
    {"name": "Attic", "trvs": 0, "window": None, "warm": 16.0},
]

# Local test HA only: never route through a system proxy
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def slug(name: str) -> str:
    return name.lower().replace(" ", "_")


class Api:
    def __init__(self, url: str, token: str | None = None) -> None:
        self.url = url.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None, form: bool = False):
        headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, method=method, data=data, headers=headers)
        try:
            with _OPENER.open(req, timeout=30) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as err:
            sys.exit(f"{method} {path} failed: {err.code} {err.read().decode(errors='replace')}")
        except urllib.error.URLError as err:
            sys.exit(f"Cannot reach {self.url}: {err.reason}")

    def step(self, base: str, flow_id: str, data: dict) -> dict:
        result = self.call("POST", f"{base}/{flow_id}", data)
        if result.get("errors"):
            sys.exit(f"Form errors at step {result.get('step_id')}: {result['errors']}")
        return result


def wait_for(url: str, seconds: int) -> None:
    """Wait until HA answers /api/onboarding (no auth needed)."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with _OPENER.open(url.rstrip("/") + "/api/onboarding", timeout=5) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() > deadline:
            sys.exit(f"Home Assistant at {url} did not come up within {seconds} s")
        time.sleep(5)


def onboard(api: Api, username: str, password: str) -> None:
    """Finish every onboarding step and log in as the new owner."""
    pending = {s["step"] for s in api.call("GET", "/api/onboarding") if not s["done"]}
    if "user" not in pending:
        sys.exit("Onboarding was already done: use --token with a long-lived access token instead.")
    client_id = api.url + "/"
    user = api.call(
        "POST",
        "/api/onboarding/users",
        {"client_id": client_id, "name": username.title(), "username": username, "password": password, "language": "en"},
    )
    token = api.call(
        "POST",
        "/auth/token",
        {"grant_type": "authorization_code", "code": user["auth_code"], "client_id": client_id},
        form=True,
    )
    api.token = token["access_token"]
    if "core_config" in pending:
        api.call("POST", "/api/onboarding/core_config", {})
    if "analytics" in pending:
        api.call("POST", "/api/onboarding/analytics", {})
    if "integration" in pending:
        api.call("POST", "/api/onboarding/integration", {"client_id": client_id, "redirect_uri": client_id + "?auth_callback=1"})
    print(f"Onboarding done, owner '{username}' created")


def room_steps(room: dict, windows: bool = True) -> list[dict]:
    """The room form steps: room and temperatures, sensors, how it starts (Eco all day)."""
    key = slug(room["name"])
    count = room["trvs"]
    sensors = {
        "temperature_sensor": f"sensor.sim_{key}_temperature",
        "trvs": [f"climate.sim_{key}_trv_{i}" for i in range(1, count + 1)],
        "external_temperature_inputs": [f"number.sim_{key}_trv_{i}_external_temperature" for i in range(1, count + 1)],
    }
    if windows:
        sensors.update({
            "window_sensors": [room["window"]] if room["window"] else [],
            "window_open_delay": 30,
            "window_close_delay": 15,
        })
    return [
        {
            "name": room["name"],
            "eco_temperature": 15.0,
            "warm_temperature": room["warm"],
            "overshoot_buffer": 1.0,
            "min_temp": 5.0,
            "max_temp": 25.0,
            "target_temp_step": "0.5",
        },
        sensors,
        {"initial_schedule": "eco"},
    ]


def create_heating(api: Api, source: str) -> str:
    existing = [e for e in api.call("GET", "/api/config/config_entries/entry") if e["domain"] == DOMAIN]
    if existing:
        sys.exit(
            f"A {DOMAIN} entry already exists ({existing[0]['title']}). "
            "Delete it in Settings > Devices & services first."
        )

    flow = "/api/config/config_entries/flow"
    result = api.call("POST", flow, {"handler": DOMAIN})
    fid = result["flow_id"]
    title = "Sim heating (relay)" if source == "switch" else "Sim heating"
    api.step(flow, fid, {"name": title, "heat_source_type": source})
    if source == "switch":
        api.step(flow, fid, {"heat_source_entity": "switch.sim_boiler_relay", "hysteresis": 0.3})
    else:
        api.step(flow, fid, {"heat_source_entity": "climate.sim_boiler", "ch_switch": "switch.sim_ch_enabled"})
    # v2: setup asks for the first room only, then points to Features
    first, *rest = ROOMS
    for step in room_steps(first, windows=False):
        result = api.step(flow, fid, step)
    if result.get("type") != "create_entry":
        sys.exit(f"Config flow did not finish: {result}")
    entry_id = result["result"]["entry_id"]
    print(f"Created '{title}' ({entry_id}) with room {first['name']}")
    created = entry_id

    enable_features(api, entry_id)

    sub = "/api/config/config_entries/subentries/flow"
    for room in rest:
        start = api.call("POST", sub, {"handler": [entry_id, "room"]})
        for step in room_steps(room):
            done = api.step(sub, start["flow_id"], step)
        if done.get("type") != "create_entry":
            sys.exit(f"Room {room['name']} did not finish: {done}")
        print(f"  added room {room['name']} ({room['trvs']} TRVs)")
    return created


FEATURES_OFF = {
    "feature_presence": False, "feature_windows": False, "feature_sun_assist": False,
    "feature_guest_mode": False, "experimental": False,
}


def options(api: Api, entry_id: str, page: str) -> tuple[str, dict]:
    """Open the options menu and go to one of its pages."""
    flow = "/api/config/config_entries/options/flow"
    start = api.call("POST", flow, {"handler": entry_id})
    return start["flow_id"], api.step(flow, start["flow_id"], {"next_step_id": page})


def enable_features(api: Api, entry_id: str) -> None:
    """Features page: presence and away, windows, sun assist, guest mode; then their pages."""
    flow = "/api/config/config_entries/options/flow"
    fid, _ = options(api, entry_id, "features")
    step = api.step(flow, fid, {
        **FEATURES_OFF, "feature_presence": True, "feature_windows": True,
        "feature_sun_assist": True, "feature_guest_mode": True,
    })
    step = api.step(flow, fid, {"presence_entity": "input_boolean.sim_somebody_home", "away_mode": "off"})
    rooms = {o["label"]: o["value"] for f in step["data_schema"] if f["name"] == "sun_rooms"
             for o in f["selector"]["select"]["options"]}
    done = api.step(flow, fid, {
        "sun_forecast": "weather.sim_weather",
        "sun_conditions": ["sunny", "partlycloudy"],
        "sun_mild_above": 12,
        "sun_rooms": [rooms[n] for n in ("Office",) if n in rooms],
        "sun_hold_temperature": 15,
        "sun_window_start": "05:00:00",
        "sun_window_end": "12:00:00",
        "sun_cold_below": 16,
        "sun_dark_below": 1000,
        "sun_check_delay": 60,
    })
    if done.get("type") != "create_entry":
        sys.exit(f"Features did not finish: {done}")
    print("  features on: presence and away, windows, sun assist (Office), guest mode")


# A week per room (Monday first), Sleep at night where the room uses it
WEEKDAY = [("00:00", "sleep"), ("06:30", "warm"), ("08:30", "eco"), ("17:00", "warm"), ("22:30", "sleep")]
WEEKEND = [("00:00", "sleep"), ("08:00", "warm"), ("13:00", "eco"), ("16:00", "warm"), ("23:00", "sleep")]
OFFICE = [("00:00", "eco"), ("08:00", "warm"), ("17:00", "off")]


def add_schedules(api: Api) -> None:
    """A Sleep preset (not used in the office) and a week per room, through the card's actions."""
    # Every room add reloads the heating system: wait until all rooms are back
    for _ in range(60):
        states = {s["entity_id"]: s for s in api.call("GET", "/api/states")}
        climates = {s["attributes"].get("friendly_name"): eid for eid, s in states.items()
                    if eid.startswith("climate.") and "schedule_state" in s["attributes"]
                    and s["state"] != "unavailable"}
        if len(climates) == len(ROOMS):
            break
        time.sleep(1)
    else:
        sys.exit(f"Only {len(climates)} of {len(ROOMS)} rooms came up: {sorted(climates)}")
    temps = {eid: {"sleep": None if name == "Office" else 16.0} for name, eid in climates.items()}
    api.call("POST", f"/api/services/{DOMAIN}/set_presets", {
        "presets": [{"id": "eco", "name": "Eco"}, {"id": "warm", "name": "Warm"},
                    {"id": "sleep", "name": "Sleep", "color": "#9b8bd6"}],
        "temperatures": temps,
    })
    for name, eid in climates.items():
        days = [OFFICE] * 5 + [[("00:00", "eco")]] * 2 if name == "Office" else [WEEKDAY] * 5 + [WEEKEND] * 2
        week = [[{"time": t, "preset": p} for t, p in day] for day in days]
        api.call("POST", f"/api/services/{DOMAIN}/set_schedule", {"entity_id": eid, "week": week})
        api.call("POST", "/api/services/climate/set_hvac_mode", {"entity_id": eid, "hvac_mode": "heat"})
    print(f"  Sleep preset and a week schedule for {', '.join(sorted(climates))}; rooms set to heat")


# Learning features page: every field, pointed at the sim entities
LEARNING_FIELDS = {
    "exp_comfort_weekday": "07:30:00",
    "exp_comfort_weekend": "08:00:00",
    "exp_outdoor": "sensor.sim_outdoor_temperature",
    "exp_weather": "weather.sim_weather",
    "exp_people": "zone.home",
    "exp_gas": "sensor.sim_gas_meter",
    "exp_flame": "binary_sensor.sim_boiler_flame",
    "exp_dhw": "binary_sensor.sim_hot_water_active",
    "exp_ch_active": "binary_sensor.sim_central_heating_active",
    "exp_water": "sensor.sim_boiler_water_temperature",
    "exp_return": "sensor.sim_boiler_return_water_temperature",
    # The number that sets the limit, as with thermostat.yaml
    "exp_max_ch": "number.sim_central_heating_max_flow_temperature",
    # What the thermostat asks for, as thermostat.yaml's flow_request sensor
    "exp_flow_request": "sensor.sim_boiler_flow_request",
    # A sensor, never a writable number
    "exp_dhw_setpoint": "sensor.sim_boiler_hot_water_setpoint",
    "exp_kp": "number.sim_central_heating_kp",
    "exp_ki": "number.sim_central_heating_ki",
    "exp_kd": "number.sim_central_heating_kd",
    "exp_integral": "sensor.sim_central_heating_pid_integral",
    "exp_gas_price_before6": "sensor.sim_gas_price_tomorrow_before_6",
    "exp_gas_price_after6": "sensor.sim_gas_price_tomorrow_after_6",
}


def set_speed(api: Api, speed: float) -> None:
    api.call("POST", "/api/services/number/set_value", {"entity_id": "number.sim_speed", "value": speed})
    print(f"  sim speed {speed:g} ({'real time' if speed == 1 else f'one hour in {60 / speed:g} min'})")


def enable_learning(api: Api, entry_id: str, source: str, auto_apply: bool, notify: str) -> None:
    """Options: Features, switch the learning features on, fill their page."""
    flow = "/api/config/config_entries/options/flow"
    fid, features = options(api, entry_id, "features")
    current = {f["name"]: f.get("description", {}).get("suggested_value") for f in features["data_schema"]}
    step = api.step(flow, fid, {**FEATURES_OFF, **{k: bool(v) for k, v in current.items()}, "experimental": True})
    start = {"flow_id": fid}
    living = next(o["value"] for f in step["data_schema"] if f["name"] == "exp_room"
                  for o in f["selector"]["select"]["options"] if o["label"] == "Living Room")
    done = api.step(
        flow,
        start["flow_id"],
        {
            "exp_room": living,
            **LEARNING_FIELDS,
            "exp_auto_apply": auto_apply,
            "exp_notify": notify,
        },
    )
    if done.get("type") != "create_entry":
        sys.exit(f"Learning features options did not finish: {done}")
    mode = "applying PID advice" if auto_apply else "observe only"
    print(f"  learning features on, following Living Room, {mode}, evening notification: {notify}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8124")
    parser.add_argument("--token", help="Long-lived access token (Profile > Security)")
    parser.add_argument("--onboard", action="store_true", help="Do onboarding first on a fresh HA")
    parser.add_argument("--username", default="test")
    parser.add_argument("--password", default="testtest")
    parser.add_argument("--wait", type=int, default=0, help="Seconds to wait for HA to come up")
    parser.add_argument("--source", choices=["climate", "switch"], default="climate")
    parser.add_argument(
        "--learning", "--experimental", dest="learning", action="store_true",
        help="Switch on the learning features with every field pointed at the sim",
    )
    parser.add_argument("--auto-apply", action="store_true", help="With --learning: apply PID advice automatically")
    parser.add_argument(
        "--notify", choices=["off", "events", "summary", "full"], default="events",
        help="With --learning: evening notification (default events)",
    )
    parser.add_argument(
        "--speed", type=float,
        help="Sim seconds per real second, 1 to 600 (default: 1 with --learning, else unchanged)",
    )
    args = parser.parse_args()
    if not args.token and not args.onboard:
        parser.error("give --token, or --onboard on a fresh Home Assistant")

    if args.wait:
        wait_for(args.url, args.wait)
    api = Api(args.url, args.token)
    if args.onboard:
        onboard(api, args.username, args.password)
    entry_id = create_heating(api, args.source)
    add_schedules(api)
    if args.learning:
        enable_learning(api, entry_id, args.source, args.auto_apply, args.notify)
    speed = args.speed if args.speed is not None else (1 if args.learning else None)
    if speed is not None:
        set_speed(api, speed)
    print("Done. Open the Heating Control Card: Rooms, Today and Week.")


if __name__ == "__main__":
    main()
