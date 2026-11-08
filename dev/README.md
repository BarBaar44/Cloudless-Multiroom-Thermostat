# Test environment

A throwaway Home Assistant with a simulated house, to try Cloudless Multiroom Thermostat without touching a real heating system.

Nothing here controls real hardware. The `heating_sim` integration fakes everything:

| What | Entities |
|---|---|
| Room temperature sensors | `sensor.sim_<room>_temperature` |
| TRVs (regulate their own valve) | `climate.sim_<room>_trv_<n>` |
| TRV external temperature inputs | `number.sim_<room>_trv_<n>_external_temperature` |
| Boiler thermostat with a PID, like [`thermostat.yaml`](../thermostat.yaml) | `climate.sim_boiler` |
| Its settings, like the numbers in `thermostat.yaml` | `number.sim_central_heating_max_flow_temperature`, `number.sim_central_heating_kp`, `_ki`, `_kd` |
| What the PID is doing | `sensor.sim_central_heating_pid_result`, `sensor.sim_central_heating_pid_integral` |
| Boiler readings | `sensor.sim_boiler_water_temperature`, `sensor.sim_boiler_return_water_temperature`, `sensor.sim_boiler_flow_request`, `sensor.sim_boiler_relative_modulation`, `sensor.sim_boiler_burner_power`, `sensor.sim_boiler_burner_starts` |
| Hot water temperature on the boiler (read only on purpose) | `sensor.sim_boiler_hot_water_setpoint` |
| Boiler relay (on/off heat source) | `switch.sim_boiler_relay` |
| Central heating enable | `switch.sim_ch_enabled` |
| Boiler signals | `binary_sensor.sim_boiler_flame`, `binary_sensor.sim_central_heating_active`, `binary_sensor.sim_hot_water_active` |
| Gas meter (m³) | `sensor.sim_gas_meter` |
| Gas prices for tomorrow | `sensor.sim_gas_price_tomorrow_before_6`, `sensor.sim_gas_price_tomorrow_after_6` |
| Outdoor temperature and weather with an hourly forecast | `sensor.sim_outdoor_temperature`, `weather.sim_weather` |
| Windows, presence and a shower (toggle these yourself) | `input_boolean.sim_living_room_garden_door`, `input_boolean.sim_master_bedroom_window`, `input_boolean.sim_somebody_home`, `input_boolean.sim_hot_water` |
| How fast the sim runs | `number.sim_speed` |

Rooms: Living Room (3 TRVs, garden door), Office, Sports Room, Master Bedroom (2 TRVs, window) and Attic (no TRVs, only adds demand). These five are added to the heating system by `setup_heating.py`.

Two spare rooms are simulated but not added, so you can try "Add room" in the UI with real entities to pick:

| Spare room | Temperature sensor | TRVs | External inputs | Window |
|---|---|---|---|---|
| Guest Room | `sensor.sim_guest_room_temperature` | `climate.sim_guest_room_trv_1`, `_trv_2` | `number.sim_guest_room_trv_1_external_temperature`, `_trv_2_` | `input_boolean.sim_guest_room_window` |
| Bathroom | `sensor.sim_bathroom_temperature` | `climate.sim_bathroom_trv_1` | `number.sim_bathroom_trv_1_external_temperature` | none |

## How the house behaves

It is built to act like the house this integration was made in, so the learning features have something real to learn from.

- **Thermostat.** `climate.sim_boiler` works like `thermostat.yaml`: its PID compares the target it gets from the integration with the winning room temperature, and asks the boiler for a flow temperature of its output times the flow limit (40 °C by default). Change Kp, Ki or Kd and warm-ups really change.
- **Boiler.** It can't burn lower than 6.1 kW. When the open radiators take less than that, the water overheats, the burner stops, and it may only start again after 5 minutes. One room heating alone makes it start and stop often; several rooms together run smoother. You can watch this in `sensor.sim_boiler_burner_starts`.
- **Rooms.** A room warms up when the water is hotter than the room and its TRVs are open, and cools towards the outdoor temperature, faster with a window open. A TRV opens when its target is above what it measures: the external input when it got one in the last 2 hours, otherwise its own sensor, which reads 1.5 °C warm like a real TRV on a radiator.
- **Shower.** Turning on `input_boolean.sim_hot_water` makes the burner heat hot water. Central heating waits until it is off, as on a combi boiler.
- **Gas.** The meter counts gas from what the burner burns, plus a fixed amount per minute of hot water.

All of it lives in `config/custom_components/heating_sim/model.py`, without Home Assistant, so it can be tried on its own: `python3 dev/config/custom_components/heating_sim/model.py` prints a warm-up.

## Speed

`number.sim_speed` is how many sim seconds pass per real second. At 30 one hour passes in two minutes, handy for trying rooms, windows and presence. **The learning features need 1 (real time):** they time warm-ups in real minutes, so at higher speeds every warm-up is too short to count. Change it any time; the value is kept over a restart.

## Start

Two options: Docker on any machine, or a VM in Virtual Machine Manager (libvirt/KVM).

### Option 1: Docker

Requires Docker.

```bash
cd dev
docker compose up -d
```

Open http://localhost:8124 (port 8124 so it never clashes with a real HA on 8123) and finish onboarding.

The integration is mounted read only from `../custom_components/`, so after changing its code: `docker compose restart`.

### Option 2: VM in Virtual Machine Manager (Fedora)

`vm/create-vm.sh` builds a Debian 13 VM on your machine and lets cloud-init do the rest: it installs Docker, clones this repo, starts the same test HA and, unless you pass `--no-setup`, does onboarding, creates the heating system with all rooms, switches on the learning features with every field filled in, and sets the sim to real time. The VM shows up in Virtual Machine Manager like any other.

```bash
sudo dnf install virt-install qemu-img   # once, if not installed yet
cd dev/vm
./create-vm.sh                           # VM "cmt-test", runs the branch you have checked out
./create-vm.sh --auto-apply              # also let it apply PID advice by itself
```

It asks for sudo (disks live in `/var/lib/libvirt/images`), downloads the Debian cloud image once (~400 MB), and prints the VM's address. First boot takes about 5 to 10 minutes, then:

- Home Assistant: `http://<vm-ip>:8124`, login `test` / `testtest`
- SSH: `ssh test@<vm-ip>` (your `~/.ssh/id_ed25519.pub` or `id_rsa.pub` is added, password works too)
- Follow the first boot: `ssh test@<vm-ip> sudo tail -f /var/log/cloud-init-output.log`
- Pull new code from the branch and restart HA: `ssh test@<vm-ip> sudo cmt-update`
- Remove: `./create-vm.sh --delete`

Options: `--name`, `--branch`, `--memory`, `--vcpus`, `--disk`, `--username`, `--password`, `--ssh-key`, `--speed` (default 1), `--auto-apply`, `--notify` (off, events, summary or full; default events), `--no-setup`. Another storage pool: `CMT_IMAGES=/path ./create-vm.sh`. The VM runs the `stable` Home Assistant image, so it tests against the current HA release.

## Add the heating system

On the VM this is already done for you (unless `--no-setup`).

Either through the UI (Settings > Devices & services > Add integration > Cloudless Multiroom Thermostat, then "Add room" per room), or with the script, which runs the same forms through the API:

1. Create a long-lived access token: your profile > Security > Long-lived access tokens.
2. Run:

```bash
python3 setup_heating.py --token <token>                       # boiler thermostat (climate)
python3 setup_heating.py --token <token> --source switch       # on/off relay instead
python3 setup_heating.py --token <token> --learning            # plus the learning features, real time
python3 setup_heating.py --token <token> --learning --auto-apply --notify full
```

On a fresh HA it can do onboarding as well: `python3 setup_heating.py --onboard --username test --password testtest`.

It creates "Sim heating" with all five rooms, presence `input_boolean.sim_somebody_home`, away mode off. With `--learning` it fills every field on the learning features page with a sim entity, following Living Room. Only one entry at a time: delete it first to switch heat source type.

## Things to try

- Set rooms to Heat and watch `sensor.sim_heating_winning_room`: the room with the biggest gap wins, its TRVs get the +1 °C buffer, `climate.sim_boiler` gets its target and starts asking for heat.
- Heat only the Master Bedroom and watch the burner start and stop; then heat the Living Room as well and see it calm down.
- Turn on `input_boolean.sim_living_room_garden_door`: after 30 s the living room pauses (`binary_sensor.living_room_paused`), its TRVs go to 10 °C; turn it off and it resumes.
- Turn off `input_boolean.sim_somebody_home`: all rooms pause and the CH switch goes off; turn it on and everything returns.
- Presets eco and warm on the room climates, pause/resume services, `set_all_off`.
- Learning features (at speed 1): a warm-up of the Living Room becomes an episode with water temperatures, overshoot and PID advice; with `--auto-apply` the advice is written to `number.sim_central_heating_kp` or `_ki` and checked on the next warm-ups. The evening report is in `sensor.sim_heating_learning_features_report`; call `cloudless_multiroom_thermostat.experimental_report` for one now. The night prediction runs at 21:00. Gas per degree-day needs a few real days of history, so it stays `unknown` at first. See [../docs/experimental.md](../docs/experimental.md).
- Restart HA: rooms come back in the same mode, preset and target. The sim itself starts over (room temperatures from the config), but its settings (Kp, Ki, Kd, flow limit, speed) are kept.

## Tuning the simulation

In `config/configuration.yaml` under `heating_sim`:

- `outdoor_temperature`, `speed` (first start only), `tick_seconds`
- `boiler`: `min_kw`, `max_kw`, `anti_cycle_minutes`, `relay_flow_temperature` (the relay boiler's fixed flow), `hot_water_setpoint`
- per room: `start_temperature`, `trvs`, `heat_rate` (°C per hour with all valves open and the water 20 °C above the room), `radiator_kw` (heat the radiators take from the water then; default 1 per TRV), `loss_rate`, `window`
- `process_value`: the sensor the thermostat's PID reads, `gas_price_before_6`, `gas_price_after_6`

Restart after changes.

## Reset

```bash
docker compose down
git clean -fdX config/   # removes the test HA's database, users and entries
```
