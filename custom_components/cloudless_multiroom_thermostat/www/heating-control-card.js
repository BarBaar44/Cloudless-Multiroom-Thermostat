/*
 * Heating Control Card
 * One Lovelace card for every room of Cloudless Multiroom Thermostat and the
 * boiler behind them. Ships with the integration, which serves this file and
 * registers it as a dashboard resource:
 * https://github.com/BarBaar44/Cloudless-Multiroom-Thermostat
 *
 * Header: the room the boiler is heating for (the winner), its current and
 * target temperature, what the boiler is doing, schedule and pressure notes.
 * Rows: one per room climate, each with room temperature, target with - and
 * +, Heat/Off, and its role (heating, heating along, waiting, reached, off,
 * paused).
 *
 * What it reads from that backend:
 *  - The room climates of the Cloudless Multiroom Thermostat integration:
 *    the single source of truth per room, the card only ever writes here.
 *    Their attributes say which room is the winner (is_winner), each room's
 *    role (role: winner, passenger, calls_for_heat, waiting, reached,
 *    paused, off) and why a room is paused (paused_reason: window, away,
 *    manual). A waiting room is below target but does not drive the heat
 *    source: it only heats along while another room drives, so it is never
 *    shown as demand.
 *  - binary_sensor.main_thermostat_central_heating_active / ..._domestic_hot_
 *    water_active: the mode the boiler is in. CH active alone does not mean
 *    the burner fires: it can just be pumping water that is already warm.
 *  - binary_sensor.diyless_thermostat_flame_on: whether the burner fires.
 *    Heating = CH active + flame, Pumping = CH active without flame.
 *    Without a flame entity, CH active counts as heating.
 *  - sensor.thermostat_relative_modulation_level: burner load while it fires.
 *  - When the boiler entity is unavailable or unknown the ESPHome thermostat
 *    is offline: the header says so instead of guessing "idle". The rows keep
 *    working, the virtual thermostats live in HA itself.
 *  - switch.main_thermostat_central_heating_enabled: owned by the Heating
 *    Schedule. The card reports it, never touches it.
 *  - sensor.thermostat_water_pressure_in_ch_circuit: low and high pressure
 *    warnings (the safety valve opens at 3 bar).
 *  - water_flow (optional, e.g. sensor.watermeterkit_water_meter_kit_current_
 *    usage): L/min, 0 when no water flows. Shown only while it is above 0.
 *    "Hot water at 6.2 L/min" during a hot water run, else "Cold water at
 *    4.0 L/min". With no winning room it replaces the status line, else it
 *    is a small line under the room's temperatures.
 *  - binary_sensor.main_thermostat_fault_indication: OpenTherm fault flag.
 *    When on, the whole card turns red and a banner says so first. OpenTherm
 *    sends only this one bit, not the code on the boiler display, so the
 *    card does not try to interpret it.
 *
 * Schedules (v2.0, the integration runs them; the card shows and edits):
 *  - Each row gets a schedule line and a today strip from the room's
 *    attributes schedule_state, schedule (the week), next_change, override,
 *    sun_assist and presets (names and colours). A room without a schedule is
 *    hatched, holds the temperature without schedule and offers only Make
 *    schedule and Scheduling off.
 *  - Tapping the target opens "Keep this until" (next schedule change, 1 hour,
 *    3 hours, until I change it, keep when everyone is away): set_override.
 *    The - and + buttons set the target until the next schedule change.
 *  - Header pills: Schedule / Suspended (suspend_schedules, resume_schedules)
 *    and Guest mode (the integration's guest switch, set_guest_mode).
 *
 * Setpoint taps are batched per room: the new target shows at once and one
 * climate.set_temperature goes out 0.8 s after the last tap.
 *
 * Originally https://github.com/BarBaar44/Heating-Control-Card  (MIT)
 */

const VERSION = "2.0.0";

const INTEGRATION = "cloudless_multiroom_thermostat";
// Room roles the integration sets (attribute `role`, thermostat v1.1.0+).
const ROLES = ["winner", "passenger", "calls_for_heat", "waiting", "reached", "paused", "off"];

const DEFAULTS = {
  title: "Heating",
  // null: every room climate of the integration, sorted by name.
  thermostats: null,
  boiler: "binary_sensor.main_thermostat_central_heating_active",
  hot_water: "binary_sensor.main_thermostat_domestic_hot_water_active",
  flame: "binary_sensor.diyless_thermostat_flame_on",
  modulation: "sensor.thermostat_relative_modulation_level",
  ch_enabled: "switch.main_thermostat_central_heating_enabled",
  pressure: "sensor.thermostat_water_pressure_in_ch_circuit",
  pressure_min: 1.4,
  pressure_max: 2.7,
  fault: "binary_sensor.main_thermostat_fault_indication",
  // Optional water meter in L/min; null hides the flow entirely.
  water_flow: null,
  step: null,
  on_mode: null,
  show_off: true,
  // Any CSS color ("#ff9800", "orange", "var(--orange-color)") or [r, g, b].
  // Unset keys keep the defaults in COLORS.
  colors: null,
};

// colors key -> CSS variable and default.
const COLORS = {
  heating: ["--hc-fire", "#ff5722"],
  hot_water: ["--hc-dhw", "var(--amber-color, #ffb300)"],
  pumping: ["--hc-pump", "var(--disabled-color, #9e9e9e)"],
  idle: ["--hc-idle", "var(--disabled-color, #9e9e9e)"],
  offline: ["--hc-offline", "var(--disabled-color, #9e9e9e)"],
  fault: ["--hc-err", "var(--error-color, #db4437)"],
  warning: ["--hc-warn", "var(--error-color, #db4437)"],
  room: ["--hc-heat", "var(--state-climate-heat-color, #ff8100)"],
  water: ["--hc-water", "var(--light-blue-color, #03a9f4)"],
  // v2 (#130): primary buttons, selection and focus in the card and its dialogs
  accent: ["--hc-accent", "#ff8100"],
  // Changes by hand that expire, on rows and the today strip
  override: ["--hc-override", "#ffb26b"],
};

// Preset colours when a preset has none of its own (set in the presets dialog).
const PRESET_COLORS = { eco: "#2f8f83", warm: "#ff8100", off: "#3d3d3d" };
const PALETTE = ["#9b8bd6", "#5c9ded", "#d6a23a", "#c76fa8", "#6fbf73", "#e07a5f", "#8d99ae", "#4db6ac"];
const SUN = "#f5c242";

const cssColor = (v) => {
  if (Array.isArray(v) && v.length === 3 && v.every((n) => num(n) !== null)) return `rgb(${v.map(Number).join(",")})`;
  return typeof v === "string" && v.trim() ? v.trim() : null;
};

const BAD = ["unknown", "unavailable", "none", ""];
const num = (v) => (v === undefined || v === null || v === "" || isNaN(Number(v)) ? null : Number(v));
const fmt = (v, d = 1) => (num(v) === null ? "--" : Number(v).toFixed(d));
const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
const pad = (n) => String(n).padStart(2, "0");
// Local wall time of an ISO time from the integration, e.g. 17:00
const hhmm = (iso) => {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : "";
};
const minutes = (t) => {
  const [h, m] = String(t).split(":").map(Number);
  return h * 60 + m;
};

// Presets of a room: id -> { name, color, temperature } (attribute presets).
function presetMap(a) {
  const out = { off: { name: "Off", color: PRESET_COLORS.off, temperature: null } };
  (a.presets || []).forEach((p, i) => {
    out[p.id] = { name: p.name, color: p.color || PRESET_COLORS[p.id] || PALETTE[(i - 2 + PALETTE.length) % PALETTE.length], temperature: p.temperature };
  });
  return out;
}

// Today's blocks [start, end, preset] in minutes from a week (Monday first),
// with the point in force at midnight carried over from earlier days.
function todayBlocks(week, now = new Date()) {
  if (!Array.isArray(week) || week.length !== 7) return [];
  const day = (now.getDay() + 6) % 7;
  let carry = null;
  for (let back = 1; back <= 7 && !carry; back++) {
    const pts = week[(day - back + 7) % 7] || [];
    if (pts.length) carry = pts[pts.length - 1].preset;
  }
  const pts = (week[day] || []).map((p) => [minutes(p.time), p.preset]);
  if (!pts.length || pts[0][0] > 0) pts.unshift([0, carry || (pts[0] && pts[0][1])]);
  return pts.map(([start, preset], i) => [start, i + 1 < pts.length ? pts[i + 1][0] : 1440, preset]);
}

const STYLE = `
  :host {
${Object.values(COLORS).map(([v, d]) => `    ${v}: ${d};`).join("\n")}
    --hc-soft: var(--secondary-background-color, rgba(127,127,127,.15));
  }
  ha-card { container-type: inline-size; padding: 12px; box-sizing: border-box; display: flex; flex-direction: column; gap: 10px; }
  button {
    border: none; font: inherit; cursor: pointer; padding: 0;
    display: flex; align-items: center; justify-content: center;
    -webkit-tap-highlight-color: transparent;
  }
  button:disabled { opacity: .35; cursor: default; }

  /* Header */
  .head { display: flex; align-items: center; gap: 10px; }
  .icon {
    width: 44px; height: 44px; border-radius: 50%; flex: none;
    color: var(--hc-idle); background: color-mix(in srgb, var(--hc-idle) 15%, transparent);
    transition: background .3s, color .3s; position: relative;
  }
  .pumping .head .icon { color: var(--hc-pump); background: color-mix(in srgb, var(--hc-pump) 15%, transparent); }
  .dhw .head .icon { color: var(--hc-dhw); background: color-mix(in srgb, var(--hc-dhw) 15%, transparent); }
  .coldwater .head .icon { color: var(--hc-water); background: color-mix(in srgb, var(--hc-water) 15%, transparent); }
  /* Cold water: hide the icon's own drop and let a drop fall from the spout. */
  #drip {
    display: none; position: absolute; left: 27px; top: 23px; width: 4px; height: 4px; pointer-events: none;
    background: currentColor; border-radius: 0 50% 50% 50%; transform: rotate(45deg);
  }
  .coldwater #flame { clip-path: polygon(0 0, 100% 0, 100% 58%, 66% 58%, 66% 100%, 0 100%); }
  .coldwater #drip { display: block; animation: drop 1.1s ease-in infinite; }
  .burning .head .icon { color: var(--hc-fire); background: color-mix(in srgb, var(--hc-fire) 20%, transparent); }
  .alert .head .icon { color: var(--hc-warn); background: color-mix(in srgb, var(--hc-warn) 20%, transparent); }
  .offline .head .icon { color: var(--hc-offline); background: color-mix(in srgb, var(--hc-offline) 15%, transparent); }
  /* Animations run only while the header shows the flame or shower head:
     fault and pressure warnings keep their own static icon. Offline never
     sets burning or dhw. */
  .burning:not(.fault):not(.alert) #flame { animation: flicker 1.6s ease-in-out infinite; transform-origin: 50% 90%; }
  .dhw:not(.fault):not(.alert) #flame { animation: shower 0.7s ease-out infinite; }
  .htext { flex: 1; min-width: 0; cursor: pointer; }
  .title { font-size: 12px; letter-spacing: .04em; text-transform: uppercase; color: var(--secondary-text-color); }
  .winner { font-size: 18px; font-weight: 600; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .burning .winner { color: var(--hc-fire); }
  .sub { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  .note { display: none; align-items: center; gap: 6px; cursor: pointer; font-size: 12px; padding: 6px 8px; border-radius: 8px; }
  .note ha-icon { --mdc-icon-size: 16px; flex: none; }
  .note.show { display: flex; }
  #warn { color: var(--hc-warn); background: color-mix(in srgb, var(--hc-warn) 12%, transparent); }
  #fault {
    display: none; align-items: center; gap: 10px; cursor: pointer;
    padding: 10px 12px; border-radius: 10px; color: #fff; background: var(--hc-err);
    font-size: 14px; font-weight: 600; animation: pulse 2s ease-in-out infinite;
  }
  #fault ha-icon { --mdc-icon-size: 26px; flex: none; }
  #fault small { display: block; font-size: 12px; font-weight: 400; opacity: .9; }
  .fault #fault { display: flex; }
  ha-card.fault { border: 2px solid var(--hc-err); }
  .fault .head .icon { color: var(--hc-err); background: color-mix(in srgb, var(--hc-err) 20%, transparent); }
  .fault .winner { color: var(--hc-err); }
  #sched { color: var(--secondary-text-color); background: var(--hc-soft); }

  /* Water flow under the status line while a room wins (or a fault shows). */
  .flowline { display: none; align-items: center; gap: 3px; font-size: 12px; font-weight: 500; color: var(--hc-water); white-space: nowrap; }
  .flowline.show { display: flex; }
  .flowline.hot { color: var(--hc-dhw); }
  .flowline ha-icon { --mdc-icon-size: 14px; flex: none; }
  .flowline.show #drop { animation: drip 1.4s ease-in infinite; }
  .flowhead .winner { color: var(--hc-water); }
  .flowhead.dhw .winner { color: var(--hc-dhw); }

  /* Header pills (v2): schedule / suspended, guest mode */
  .pills { display: flex; gap: 6px; flex-wrap: wrap; }
  .pill { height: 32px; padding: 0 12px; border-radius: 16px; gap: 6px; font-size: 12px; font-weight: 500; background: var(--hc-soft); color: var(--primary-text-color); }
  .pill ha-icon { --mdc-icon-size: 16px; color: var(--hc-accent); }
  .pill.on { background: color-mix(in srgb, var(--hc-accent) 18%, transparent); }
  .pill.susp { background: color-mix(in srgb, ${SUN} 15%, transparent); color: ${SUN}; font-weight: 600; }
  .pill.susp ha-icon { color: ${SUN}; }
  #nosched { color: ${SUN}; background: color-mix(in srgb, ${SUN} 12%, transparent); }

  /* Rooms */
  .rooms { display: flex; flex-direction: column; gap: 4px; }
  .row { padding: 6px 6px 7px 10px; border-radius: 12px; border: 1px solid transparent; }
  .rgrid { display: grid; grid-template-columns: minmax(0,3fr) minmax(56px,2fr) auto 34px; align-items: center; gap: 8px; }
  .rsched { font-size: 11px; color: var(--secondary-text-color); display: none; align-items: center; gap: 3px; white-space: nowrap; overflow: hidden; }
  .rsched.show { display: flex; }
  .rsched ha-icon { --mdc-icon-size: 12px; flex: none; }
  .rsched span { overflow: hidden; text-overflow: ellipsis; }
  .rsched.manual { color: var(--hc-override); font-weight: 500; }
  .rsched.sun, .rsched.none, .rsched.susp { color: ${SUN}; }
  .rsched.none { font-weight: 600; }
  .rsched.mine { font-style: italic; }
  .strip { position: relative; height: 4px; margin-top: 7px; border-radius: 2px; background: var(--hc-soft); overflow: hidden; display: none; }
  .strip.show { display: block; }
  .strip i { position: absolute; top: 0; bottom: 0; }
  .strip i.over { background: repeating-linear-gradient(135deg, var(--hc-override) 0 4px, transparent 4px 8px); }
  .strip i.sunwait { background: repeating-linear-gradient(135deg, ${SUN} 0 4px, transparent 4px 8px); }
  .strip i.now { width: 2px; background: var(--primary-text-color); }
  .rtgt.tap { cursor: pointer; border-radius: 6px; }
  .rtgt.tap:hover { background: var(--hc-soft); }
  .row.manual .rtgt { color: var(--hc-override); }
  /* No schedule: hatched, holds the temperature without schedule, two ways out */
  .row.nosched { border: 1px dashed color-mix(in srgb, ${SUN} 50%, transparent); background: repeating-linear-gradient(135deg, color-mix(in srgb, ${SUN} 6%, transparent) 0 8px, transparent 8px 16px); }
  .row.nosched .rtgt { opacity: .55; }
  .nsbox { display: none; margin-top: 8px; }
  .row.nosched .nsbox { display: block; }
  .nsbox p { margin: 0 0 8px; font-size: 11px; color: var(--secondary-text-color); line-height: 1.4; }
  .nsbtns { display: flex; gap: 8px; }
  .btn { flex: 1; min-height: 40px; border-radius: 10px; font-size: 13px; font-weight: 600; background: var(--hc-soft); color: var(--primary-text-color); padding: 0 12px; }
  .btn.primary { background: var(--hc-accent); color: #1c1c1c; font-weight: 700; }

  /* Dialogs: over the card, full screen on a phone */
  .dlg { position: fixed; inset: 0; z-index: 10; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.55); }
  .dbox { width: min(420px, 100vw); max-height: 100vh; overflow: auto; box-sizing: border-box; padding: 18px 20px; border-radius: 20px; background: var(--card-background-color, var(--ha-card-background, #1c1c1c)); color: var(--primary-text-color); display: flex; flex-direction: column; gap: 14px; }
  @media (max-width: 500px) { .dbox { width: 100vw; height: 100vh; border-radius: 0; } }
  .dhead { display: flex; align-items: flex-start; gap: 10px; }
  .dhead > div { flex: 1; min-width: 0; }
  .dtitle { font-size: 18px; font-weight: 600; }
  .dsub { font-size: 12px; color: var(--secondary-text-color); }
  .dclose { width: 40px; height: 40px; border-radius: 50%; background: var(--hc-soft); color: var(--primary-text-color); flex: none; }
  .dset { display: flex; align-items: center; justify-content: center; gap: 18px; }
  .dset .adj { width: 48px; height: 48px; border-radius: 12px; }
  .dval { font-size: 34px; font-weight: 700; font-variant-numeric: tabular-nums; text-align: center; min-width: 110px; }
  .dval small { display: block; font-size: 12px; font-weight: 400; color: var(--secondary-text-color); }
  fieldset { border: 0; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  legend { font-size: 12px; letter-spacing: .04em; text-transform: uppercase; color: var(--secondary-text-color); margin-bottom: 6px; padding: 0; }
  .opt { display: flex; align-items: center; gap: 12px; min-height: 48px; padding: 6px 12px; border-radius: 12px; border: 1px solid var(--divider-color, #2e2e2e); cursor: pointer; }
  .opt:has(input:checked) { border-color: var(--hc-accent); background: color-mix(in srgb, var(--hc-accent) 10%, transparent); }
  .opt input { accent-color: var(--hc-accent); width: 20px; height: 20px; margin: 0; flex: none; }
  .opt span { display: flex; flex-direction: column; }
  .opt b { font-size: 14px; font-weight: 600; }
  .opt small { font-size: 12px; color: var(--secondary-text-color); }
  .opt input[type="datetime-local"] { width: auto; height: auto; accent-color: auto; font: inherit; background: var(--hc-soft); color: inherit; border: 0; border-radius: 8px; padding: 6px 8px; margin-top: 4px; }
  .dbtns { display: flex; gap: 8px; }
  .row.win { border-color: color-mix(in srgb, var(--hc-fire) 45%, transparent); background: color-mix(in srgb, var(--hc-fire) 8%, transparent); }
  .rinfo { min-width: 0; cursor: pointer; }
  .rname { font-size: 14px; font-weight: 500; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .rrole { font-size: 11px; color: var(--secondary-text-color); display: flex; align-items: center; gap: 3px; white-space: nowrap; overflow: hidden; }
  .rrole ha-icon { --mdc-icon-size: 13px; flex: none; }
  .rtext { overflow: hidden; text-overflow: ellipsis; }
  .row.win .rrole { color: var(--hc-fire); font-weight: 600; }
  .row.along .rrole { color: var(--hc-heat); }
  .row.paused .rrole { color: var(--hc-heat); }
  .row.away .rrole { color: var(--secondary-text-color); }
  /* Waiting: below target, but nothing heats it; calmer than Calls for heat. */
  .row.waiting .rrole { opacity: .7; }
  /* Room temperature is the main reading: larger and bolder than the target. */
  .rcur { display: flex; align-items: center; justify-content: center; gap: 2px; font-size: 20px; font-weight: 600; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  .rcur ha-icon { --mdi-icon-size: 16px; --mdc-icon-size: 16px; color: var(--secondary-text-color); }
  .set { display: flex; align-items: center; gap: 2px; }
  .adj { width: 28px; height: 28px; border-radius: 8px; background: var(--hc-soft); color: var(--primary-text-color); }
  .adj ha-icon { --mdc-icon-size: 18px; }
  .adj:active:not(:disabled) { transform: scale(.92); }
  .rtgt { font-size: 14px; font-weight: 500; min-width: 46px; text-align: center; color: var(--primary-text-color); }
  .row.off .rtgt, .row.paused .rtgt { opacity: .4; }
  .row.pending .rtgt { color: var(--hc-heat); opacity: 1; }
  .mode { width: 32px; height: 32px; border-radius: 50%; background: var(--hc-soft); color: var(--secondary-text-color); }
  .mode ha-icon { --mdc-icon-size: 18px; }
  .row.heat .mode { background: var(--hc-heat); color: #fff; }
  .row.paused .mode { background: var(--hc-soft); color: var(--hc-heat); opacity: 1; cursor: pointer; }
  .row.unavailable { opacity: .45; }
  /* One room: its Heat/Off sits in the header, the row loses that column. */
  #hmode { display: none; flex: none; }
  .single #hmode { display: flex; }
  .single .rgrid { grid-template-columns: minmax(0,3fr) minmax(56px,2fr) auto; }
  .single .row .mode { display: none; }
  #hmode.heat { background: var(--hc-heat); color: #fff; }
  #hmode.paused { background: var(--hc-soft); color: var(--hc-heat); opacity: 1; cursor: pointer; }
  .empty { font-size: 13px; color: var(--secondary-text-color); padding: 4px 2px; }

  @keyframes shower {
    0%   { clip-path: inset(0 0 45% 0); }
    100% { clip-path: inset(0 0 0 0); }
  }
  @keyframes drop {
    0%   { transform: translateY(0)   rotate(45deg) scale(.3); opacity: 0; }
    25%  { transform: translateY(0)   rotate(45deg) scale(1);  opacity: 1; }
    100% { transform: translateY(9px) rotate(45deg) scale(1);  opacity: 0; }
  }
  @keyframes drip {
    0%   { transform: translateY(-2px); opacity: .5; }
    60%  { transform: translateY(1px);  opacity: 1;  }
    100% { transform: translateY(2px);  opacity: .5; }
  }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .75; } }
  @keyframes flicker {
    0%   { transform: rotate(-1.5deg) scaleY(1);    opacity: .9; }
    20%  { transform: rotate(1.8deg)  scaleY(1.12); opacity: 1;  }
    40%  { transform: rotate(-.8deg)  scaleY(.94);  opacity: .8; }
    60%  { transform: rotate(1.2deg)  scaleY(1.08); opacity: 1;  }
    80%  { transform: rotate(-1.8deg) scaleY(.97);  opacity: .85;}
    100% { transform: rotate(-1.5deg) scaleY(1);    opacity: .9; }
  }
  @media (prefers-reduced-motion: reduce) { .burning #flame, .dhw #flame, #fault, #drop { animation: none !important; } .coldwater #flame { clip-path: none; } .coldwater #drip { display: none; } }
  /* Narrow card (phone, small grid cell): room name and role get the space. */
  @container (max-width: 360px) { .rgrid { gap: 4px; } .rcur { font-size: 18px; } .rcur ha-icon { display: none; } }
`;

class HeatingControlCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._rows = new Map(); // entity_id -> { el, refs, pending, timer, clear }
    this._rowKey = "";
  }

  static getConfigElement() {
    return document.createElement("heating-control-card-editor");
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    const c = { ...DEFAULTS, ...(config || {}) };
    // Keys of the old YAML setup (without the integration) do nothing anymore.
    const old = ["climate", "name", "paused", "heating_area"].filter((k) => c[k] !== undefined);
    if (old.length) console.warn(`heating-control-card: ${old.join(", ")} belonged to the YAML setup and are ignored. The card shows the rooms of Cloudless Multiroom Thermostat.`);
    if (c.thermostats && !Array.isArray(c.thermostats)) throw new Error("thermostats must be a list");
    if (c.colors != null && (typeof c.colors !== "object" || Array.isArray(c.colors))) throw new Error("colors must be a map, e.g. hot_water: orange");
    this._config = c;
    this._applyColors(c.colors || {});
    this._rows.forEach((r) => { clearTimeout(r.timer); clearTimeout(r.clear); });
    this._rows.clear();
    this._rowKey = "";
    this._build();
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  // Inline custom properties on the host beat the :host defaults.
  _applyColors(colors) {
    Object.keys(colors).forEach((k) => {
      if (!COLORS[k]) console.warn(`heating-control-card: unknown colors key "${k}". Known: ${Object.keys(COLORS).join(", ")}`);
    });
    Object.entries(COLORS).forEach(([k, [v]]) => {
      const val = cssColor(colors[k]);
      if (val) this.style.setProperty(v, val);
      else this.style.removeProperty(v);
    });
  }

  getCardSize() {
    return 2 + this._rooms().length;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _build() {
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div id="fault"><ha-icon icon="mdi:alert-octagon"></ha-icon><div>Boiler fault<small>The boiler reports a fault. Check its display; heating may not work.</small></div></div>
        <div class="head">
          <button class="icon" id="icon" title="Boiler"><ha-icon id="flame" icon="mdi:fire-off"></ha-icon><span id="drip"></span></button>
          <div class="htext" id="htext">
            <div class="title" id="title"></div>
            <div class="winner" id="winner"></div>
            <div class="sub" id="sub"></div>
            <div class="flowline" id="flowline"><ha-icon id="drop" icon="mdi:water"></ha-icon><span id="flowText"></span></div>
          </div>
          <button class="mode" id="hmode"><ha-icon id="hmicon" icon="mdi:radiator-off"></ha-icon></button>
        </div>
        <div class="pills" id="pills">
          <button class="pill" id="spill"><ha-icon icon="mdi:clock-outline"></ha-icon><span id="spillText">Schedule</span></button>
          <button class="pill" id="gpill"><ha-icon icon="mdi:account-plus-outline"></ha-icon><span id="gpillText">Guest mode</span></button>
        </div>
        <div class="note" id="nosched"><ha-icon icon="mdi:alert"></ha-icon><span id="noschedText"></span></div>
        <div class="note" id="sched"><ha-icon icon="mdi:calendar-clock"></ha-icon><span>Central heating switch is off</span></div>
        <div class="note" id="warn"><ha-icon icon="mdi:alert"></ha-icon><span id="warnText"></span></div>
        <div class="rooms" id="rooms"></div>
      </ha-card>`;
    const $ = (id) => this.shadowRoot.getElementById(id);
    this._el = {
      card: this.shadowRoot.querySelector("ha-card"),
      title: $("title"), winner: $("winner"), sub: $("sub"), flame: $("flame"),
      hmode: $("hmode"), hmicon: $("hmicon"),
      flowline: $("flowline"), flowText: $("flowText"),
      sched: $("sched"), warn: $("warn"), warnText: $("warnText"), rooms: $("rooms"),
      pills: $("pills"), spill: $("spill"), spillText: $("spillText"), gpill: $("gpill"), gpillText: $("gpillText"),
      nosched: $("nosched"), noschedText: $("noschedText"),
    };
    $("spill").addEventListener("click", () => this._suspendTap());
    $("gpill").addEventListener("click", () => this._guestDialog());
    $("nosched").addEventListener("click", () => {
      const first = this.shadowRoot.querySelector(".row.nosched");
      if (first && first.scrollIntoView) first.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    $("icon").addEventListener("click", () => this._moreInfo(this._iconTarget));
    $("htext").addEventListener("click", () => this._moreInfo(this._flowHead ? this._config.water_flow : this._winnerEntity));
    $("fault").addEventListener("click", () => this._moreInfo(this._config.fault));
    $("hmode").addEventListener("click", () => this._single && this._modeTap(this._single));
    $("flowline").addEventListener("click", (ev) => { ev.stopPropagation(); this._moreInfo(this._config.water_flow); });
    $("sched").addEventListener("click", () => this._moreInfo(this._config.ch_enabled));
    $("warn").addEventListener("click", () => this._moreInfo(this._config.pressure));
  }

  _state(id) {
    return id && this._hass ? this._hass.states[id] : undefined;
  }

  _on(id) {
    const s = this._state(id);
    return !!s && s.state === "on";
  }

  // Why a room is held off: "window", "away", "manual" or null.
  _pauseReason(room) {
    const s = this._state(room.entity);
    const reason = s && s.attributes.paused_reason;
    return reason ? String(reason) : null;
  }

  // The integration's role for a room, or null (unknown value, or a climate
  // listed by hand that is not an integration room): then the card works the
  // role out itself.
  _roleOf(room) {
    const s = this._state(room.entity);
    const role = s && s.attributes.role;
    return ROLES.includes(role) ? role : null;
  }

  // A room climate of the Cloudless Multiroom Thermostat integration.
  _isIntegration(entityId) {
    const ent = this._hass.entities && this._hass.entities[entityId];
    return !!ent && ent.platform === INTEGRATION;
  }

  // Configured rooms, else every room of the integration sorted by name.
  _rooms() {
    const c = this._config;
    if (!c || !this._hass) return [];
    let list;
    if (c.thermostats) {
      list = c.thermostats.map((t) => (typeof t === "string" ? { entity: t } : { ...t })).filter((t) => t.entity);
    } else {
      list = Object.keys(this._hass.states)
        .filter((id) => id.startsWith("climate.") && this._isIntegration(id))
        .map((entity) => ({ entity }));
    }
    list.forEach((t) => {
      const s = this._state(t.entity);
      // Named after the room itself (the climate's name), unless set here.
      t.label = t.name || (s && s.attributes.friendly_name) || t.entity;
    });
    if (!c.thermostats) list.sort((a, b) => a.label.localeCompare(b.label));
    return list;
  }

  // The header speaks for the whole house: it reads every room of the
  // integration, also the ones a `thermostats` list leaves
  // out, so a card that shows only the living room still says the boiler is
  // heating for the bedroom. The rows stay the listed rooms.
  _houseRooms(rooms) {
    if (!this._config.thermostats) return rooms;
    const listed = new Set(rooms.map((r) => r.entity));
    const extra = Object.keys(this._hass.states)
      .filter((id) => id.startsWith("climate.") && !listed.has(id) && this._isIntegration(id))
      .map((entity) => {
        const s = this._state(entity);
        const label = (s && s.attributes.friendly_name) || entity;
        return { entity, label };
      });
    return rooms.concat(extra);
  }

  // The rooms say themselves which one wins (is_winner).
  _winnerInfo(rooms) {
    const win = rooms.find((r) => {
      const s = this._state(r.entity);
      return s && s.attributes.is_winner === true;
    });
    if (!win) return { area: null, entity: null };
    const a = this._state(win.entity).attributes;
    return {
      area: win.label,
      entity: win.entity,
      target: num(a.effective_target ?? a.temperature),
      curr: num(a.current_temperature),
    };
  }

  _update() {
    if (!this._el || !this._hass) return;
    const c = this._config;
    const e = this._el;
    const rooms = this._rooms();
    const house = this._houseRooms(rooms);

    const boilerState = this._state(c.boiler);
    const flameState = this._state(c.flame);
    const offline = (!!boilerState && BAD.includes(boilerState.state)) || (!!flameState && BAD.includes(flameState.state));
    const chActive = !offline && !!boilerState && boilerState.state === "on";
    const dhw = !offline && this._on(c.hot_water);
    // Burner firing: the flame entity when there is one, else CH active.
    const firing = !offline && (flameState ? flameState.state === "on" : chActive || dhw);
    // On a combi a hot water run wins: the flame is then for the tap.
    const heating = chActive && firing && !dhw;
    const pumping = chActive && !firing && !dhw;
    const modState = this._state(c.modulation);
    const mod = firing && modState ? num(modState.state) : null;
    const chEnabledState = this._state(c.ch_enabled);
    const chDisabled = !!chEnabledState && chEnabledState.state === "off";
    const pState = this._state(c.pressure);
    const p = pState ? parseFloat(pState.state) : NaN;
    const lowP = !isNaN(p) && p < Number(c.pressure_min);
    const highP = !isNaN(p) && c.pressure_max != null && p > Number(c.pressure_max);
    const fault = !offline && this._on(c.fault);

    const w = this._winnerInfo(house);
    this._winnerEntity = w.entity;

    // Header
    e.title.textContent = c.title || "";
    const inHeat = house.filter((r) => {
      const s = this._state(r.entity);
      return s && s.state !== "off" && !BAD.includes(s.state);
    });
    const anyHeat = inHeat.length > 0;
    // Every room in heat held off by the integration (window, away, manual)
    const allPaused = anyHeat && inHeat.every((r) => this._pauseReason(r));
    const awayAll = allPaused && inHeat.every((r) => this._pauseReason(r) === "away");
    // The integration turns the central heating enable switch off itself while
    // no room that drives the heat source is heating (all paused, or only rooms
    // that heat along). Only a switch that is off while such a room is heating
    // was turned off by something else, so only then say so.
    const drives = (r) => {
      const s = this._state(r.entity);
      return !(s && (s.attributes.drives_heat_source === false || s.attributes.role === "waiting"));
    };
    const chOff = chDisabled && inHeat.some((r) => !this._pauseReason(r) && drives(r));
    // Integration roles: a calling room asks for the heat source, a waiting
    // room does not (it only heats along), so only the first counts as demand.
    const calling = inHeat.filter((r) => this._roleOf(r) === "calls_for_heat");
    const waiting = inHeat.filter((r) => this._roleOf(r) === "waiting");
    const roomsText = (list, one, many) => (list.length === 1 ? `${list[0].label} ${one}` : `${list.length} rooms ${many}`);
    const modText = mod !== null ? ` · ${Math.round(mod)}%` : "";
    let activity;
    if (offline) activity = "thermostat offline";
    else if (heating) activity = `boiler heating${modText}`;
    else if (pumping) activity = "boiler pumping";
    else if (dhw) activity = `boiler on for hot water${firing ? modText : ""}`;
    else activity = "boiler idle";
    if (offline) {
      e.winner.textContent = "Thermostat offline";
      e.sub.textContent = w.area ? `${w.area} calls for heat · boiler status unknown` : "Boiler status unknown";
    } else if (w.area) {
      e.winner.textContent = w.area;
      const temps = w.curr !== null && w.target !== null ? `${fmt(w.curr)}° → ${fmt(w.target)}°` : "";
      e.sub.textContent = [temps, activity].filter(Boolean).join(" · ");
    } else {
      // No winner: either nothing is set to heat, or every room is at target.
      e.winner.textContent = dhw ? "Hot water"
        : !anyHeat || chOff ? "Heating off"
        : awayAll ? "Heating off · nobody home"
        : allPaused ? "Heating paused"
        : calling.length ? roomsText(calling, "calls for heat", "call for heat")
        : waiting.length ? "Heating off"
        : "All rooms at target";
      const note = !chOff && !calling.length && waiting.length ? roomsText(waiting, "waiting", "waiting") : "";
      e.sub.textContent = [activity.charAt(0).toUpperCase() + activity.slice(1), note].filter(Boolean).join(" · ");
    }
    if (fault) {
      e.winner.textContent = "Boiler fault";
      e.sub.textContent = w.area ? `Heating for ${w.area} may not work` : "Heating may not work";
    }
    // Water flow: nothing at 0, unavailable or without the option.
    const flowState = this._state(c.water_flow);
    const flow = flowState ? num(flowState.state) : null;
    const flowing = flow !== null && flow > 0;
    // Hot during a hot water run, else cold; offline we cannot tell. With no
    // winning room (and no offline or fault text) the flow takes the status
    // line, else it is a small line under the temperatures.
    const flowText = flowing ? `${offline ? "Water" : dhw ? "Hot water" : "Cold water"} at ${flow.toFixed(1)} L/min` : "";
    this._flowHead = flowing && !offline && !fault && !w.area;
    if (this._flowHead) e.winner.textContent = flowText;
    const flowLine = flowing && !this._flowHead;
    e.flowline.classList.toggle("show", flowLine);
    e.flowline.classList.toggle("hot", flowLine && dhw);
    e.flowText.textContent = flowLine ? flowText : "";

    let icon = "mdi:fire-off";
    if (offline) icon = "mdi:lan-disconnect";
    else if (fault) icon = "mdi:alert-octagon";
    else if (lowP || highP) icon = "mdi:fire-alert";
    else if (heating) icon = "mdi:fire";
    else if (pumping) icon = "mdi:pump";
    else if (dhw) icon = "mdi:shower-head";
    else if (flowing) icon = "mdi:water-pump";
    e.flame.setAttribute("icon", icon);
    const coldIcon = icon === "mdi:water-pump";
    this._iconTarget = offline ? c.boiler : fault ? c.fault : dhw ? c.hot_water : coldIcon ? c.water_flow : c.flame && flameState ? c.flame : c.boiler;

    // Schedules (v2): pills and rooms without a schedule
    const scheduled = house.filter((r) => {
      const s = this._state(r.entity);
      return s && s.attributes.schedule_state !== undefined;
    });
    const suspended = scheduled.some((r) => this._state(r.entity).attributes.schedules_suspended === true);
    e.spill.style.display = scheduled.length ? "" : "none";
    e.spill.classList.toggle("susp", suspended);
    e.spill.querySelector("ha-icon").setAttribute("icon", suspended ? "mdi:pause" : "mdi:clock-outline");
    e.spillText.textContent = suspended ? "Suspended" : "Schedule";
    e.spill.setAttribute("aria-label", suspended ? "Schedules suspended, tap to resume" : "Schedules on, tap to suspend");
    this._guest = this._guestEntity();
    const gs = this._state(this._guest);
    e.gpill.style.display = gs ? "" : "none";
    const guestOn = !!gs && gs.state === "on";
    e.gpill.classList.toggle("on", guestOn);
    e.gpillText.textContent = guestOn ? (gs.attributes.until ? `Guest · until ${this._when(gs.attributes.until)}` : "Guest · on") : "Guest mode";
    e.pills.style.display = scheduled.length || gs ? "" : "none";
    const none = scheduled.filter((r) => this._state(r.entity).attributes.schedule_state === "none");
    e.nosched.classList.toggle("show", none.length > 0);
    e.noschedText.textContent = none.length
      ? `${none.length === 1 ? "1 room" : `${none.length} rooms`} without a schedule · holds ${fmt(num(this._state(none[0].entity).attributes.temperature) ?? 15, 0)}°`
      : "";

    e.sched.classList.toggle("show", chOff);
    e.warn.classList.toggle("show", lowP || highP);
    e.warnText.textContent = lowP
      ? `Low CH pressure: ${fmt(p)} bar (min ${fmt(c.pressure_min)})`
      : highP ? `High CH pressure: ${fmt(p)} bar (max ${fmt(c.pressure_max)})` : "";

    const cls = e.card.classList;
    cls.toggle("burning", heating);
    cls.toggle("dhw", dhw);
    cls.toggle("pumping", pumping);
    cls.toggle("alert", lowP || highP);
    cls.toggle("offline", offline);
    cls.toggle("fault", fault);
    cls.toggle("flowhead", this._flowHead);
    cls.toggle("coldwater", coldIcon);

    // Rows: rebuild only when the set of rooms changes, else update in place.
    const visible = rooms.filter((r) => {
      if (c.show_off !== false) return true;
      const s = this._state(r.entity);
      return !s || s.state !== "off" || r.entity === this._winnerEntity;
    });
    const key = visible.map((r) => `${r.entity}|${r.label}`).join(",");
    if (key !== this._rowKey) this._buildRows(visible, key);
    visible.forEach((r) => this._updateRow(r, { heating, pumping, offline, winner: this._winnerEntity }));

    // One room: mirror its Heat/Off button into the header.
    this._single = visible.length === 1 ? visible[0].entity : null;
    cls.toggle("single", !!this._single);
    if (this._single) {
      const f = this._rows.get(this._single).refs;
      e.hmicon.setAttribute("icon", f.micon.getAttribute("icon"));
      e.hmode.title = f.mode.title;
      e.hmode.disabled = f.mode.disabled;
      e.hmode.classList.toggle("heat", f.row.classList.contains("heat"));
      e.hmode.classList.toggle("paused", f.row.classList.contains("paused"));
    }
  }

  _buildRows(rooms, key) {
    const box = this._el.rooms;
    const keep = new Set(rooms.map((r) => r.entity));
    this._rows.forEach((r, id) => {
      if (!keep.has(id)) {
        clearTimeout(r.timer);
        clearTimeout(r.clear);
        this._rows.delete(id);
      }
    });
    box.innerHTML = rooms.length ? "" : `<div class="empty">No rooms found</div>`;
    rooms.forEach((room) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `
        <div class="rgrid">
          <div class="rinfo">
            <div class="rname">${esc(room.label)}</div>
            <div class="rrole"><ha-icon class="ricon" icon="mdi:fire"></ha-icon><span class="rtext"></span></div>
            <div class="rsched"><ha-icon class="sicon" icon="mdi:clock-outline"></ha-icon><span class="stext"></span></div>
          </div>
          <div class="rcur" title="Room temperature"><ha-icon icon="mdi:thermometer"></ha-icon><span class="rcurv"></span></div>
          <div class="set">
            <button class="adj down" title="Lower"><ha-icon icon="mdi:minus"></ha-icon></button>
            <div class="rtgt"></div>
            <button class="adj up" title="Raise"><ha-icon icon="mdi:plus"></ha-icon></button>
          </div>
          <button class="mode"><ha-icon class="micon" icon="mdi:radiator-off"></ha-icon></button>
        </div>
        <div class="strip"></div>
        <div class="nsbox">
          <p>Targets can't be changed until this room has a schedule, or you take it over yourself.</p>
          <div class="nsbtns"><button class="btn primary make">Make schedule</button><button class="btn mine">Scheduling off</button></div>
        </div>`;
      const q = (s) => row.querySelector(s);
      const refs = {
        row, ricon: q(".ricon"), rtext: q(".rtext"), cur: q(".rcurv"), tgt: q(".rtgt"), up: q(".up"), down: q(".down"),
        mode: q(".mode"), micon: q(".micon"), sched: q(".rsched"), sicon: q(".sicon"), stext: q(".stext"), strip: q(".strip"),
      };
      const prev = this._rows.get(room.entity);
      const state = { refs, pending: prev ? prev.pending : null, timer: prev ? prev.timer : null, clear: prev ? prev.clear : null, room };
      this._rows.set(room.entity, state);
      q(".rinfo").addEventListener("click", () => this._moreInfo(room.entity));
      refs.up.addEventListener("click", () => this._adjust(room.entity, 1));
      refs.down.addEventListener("click", () => this._adjust(room.entity, -1));
      refs.mode.addEventListener("click", () => this._modeTap(room.entity));
      refs.tgt.addEventListener("click", () => this._targetTap(room.entity));
      q(".make").addEventListener("click", () => this._makeDialog(room.entity));
      q(".mine").addEventListener("click", () => this._call(INTEGRATION, "set_schedule", { entity_id: room.entity, scheduling: "off" }));
      box.appendChild(row);
    });
    this._rowKey = key;
  }

  _updateRow(room, ctx) {
    const r = this._rows.get(room.entity);
    if (!r) return;
    r.room = room;
    const f = r.refs;
    const s = this._state(room.entity);
    const unavailable = !s || BAD.includes(s.state);
    const a = s ? s.attributes : {};
    const isOff = !unavailable && s.state === "off";
    // A paused room stays editable: the integration keeps its target.
    const reason = this._pauseReason(room);
    const paused = !!reason && !isOff;

    if (r.pending !== null && !r.timer && num(a.temperature) === r.pending) {
      r.pending = null;
      clearTimeout(r.clear);
    }
    const target = r.pending !== null ? r.pending : a.temperature;
    const min = a.min_temp ?? 5;
    const max = a.max_temp ?? 30;
    const below = num(a.temperature) !== null && num(a.current_temperature) !== null && num(a.current_temperature) < num(a.temperature);
    const isWinner = ctx.winner === room.entity;
    // The integration's role when it sends one, else worked out here.
    const own = this._roleOf(room);

    // Role in the two-tier model
    let role, roleIcon, along = false;
    if (unavailable) { role = "Unavailable"; roleIcon = "mdi:help-circle-outline"; }
    else if (paused && reason === "window") { role = "Paused · window open"; roleIcon = "mdi:window-open-variant"; }
    // Away is the normal state of an empty house, not something to act on:
    // a calm "Away", the header says "nobody home" for the whole house.
    else if (paused && reason === "away") { role = "Away"; roleIcon = "mdi:home-export-outline"; }
    else if (paused) { role = "Paused"; roleIcon = "mdi:pause"; }
    else if (isOff) { role = "Off"; roleIcon = "mdi:power"; }
    else if (isWinner && ctx.heating) { role = "Heating"; roleIcon = "mdi:fire"; }
    else if (isWinner && ctx.pumping) { role = "Pumping"; roleIcon = "mdi:pump"; }
    else if (isWinner) { role = "Calls for heat"; roleIcon = "mdi:fire"; }
    else if (own === "waiting") { role = "Waiting for heat"; roleIcon = "mdi:timer-sand"; }
    else if (own === "calls_for_heat") { role = "Calls for heat"; roleIcon = "mdi:thermometer-chevron-up"; }
    else if (own === "reached") { role = "Reached"; roleIcon = "mdi:check"; }
    // The heat source runs for another room; the boiler entities only say
    // whether it fires or pumps (a switch heat source has neither: heating).
    else if (own === "passenger" && ctx.pumping) { role = "Pumping along"; roleIcon = "mdi:pump"; }
    else if (own === "passenger") { role = "Heating along"; roleIcon = "mdi:radiator"; along = true; }
    else if (below && ctx.heating) { role = "Heating along"; roleIcon = "mdi:radiator"; along = true; }
    else if (below && ctx.pumping) { role = "Pumping along"; roleIcon = "mdi:pump"; }
    else if (below) { role = "Calls for heat"; roleIcon = "mdi:thermometer-chevron-up"; }
    else { role = "Reached"; roleIcon = "mdi:check"; }

    f.rtext.textContent = role;
    f.ricon.setAttribute("icon", roleIcon);
    f.cur.textContent = `${fmt(a.current_temperature)}°`;
    f.tgt.textContent = isOff && r.pending === null ? "--" : `${fmt(target)}°`;

    f.micon.setAttribute("icon", isOff ? "mdi:radiator-off" : "mdi:radiator");
    f.mode.title = isOff ? "Turn heating on" : "Turn heating off";

    const sched = this._schedLine(a);
    f.sched.classList.toggle("show", !!sched);
    f.sched.className = `rsched${sched ? ` show ${sched.cls}` : ""}`;
    f.stext.textContent = sched ? sched.text : "";
    f.sicon.setAttribute("icon", sched ? sched.icon : "mdi:clock-outline");
    this._strip(f.strip, a);
    const noSchedule = ["none", "blocked"].includes(a.schedule_state);
    const scheduledRoom = a.schedule_state === "active" || a.schedule_state === "suspended";
    f.tgt.classList.toggle("tap", scheduledRoom && !isOff && !unavailable);
    f.tgt.title = scheduledRoom ? "Keep this until…" : "";

    const locked = unavailable || isOff || noSchedule;
    f.down.disabled = locked || num(target) === null || num(target) <= min;
    f.up.disabled = locked || num(target) === null || num(target) >= max;
    f.mode.disabled = unavailable;

    const cls = f.row.classList;
    cls.toggle("win", isWinner && !paused && !isOff && !unavailable);
    cls.toggle("along", along);
    cls.toggle("waiting", role === "Waiting for heat");
    cls.toggle("heat", !isOff && !unavailable);
    cls.toggle("off", isOff);
    cls.toggle("paused", paused);
    cls.toggle("away", paused && reason === "away");
    cls.toggle("pending", r.pending !== null);
    cls.toggle("unavailable", unavailable);
    cls.toggle("nosched", a.schedule_state === "none");
    cls.toggle("manual", !!a.override);
  }

  // The schedule line under a room's role: { text, icon, cls } or null (v1 room).
  _schedLine(a) {
    const st = a.schedule_state;
    if (st === undefined) return null;
    const P = presetMap(a);
    const name = (id) => (P[id] ? P[id].name : id);
    const temp = (v) => `${fmt(v, 1).replace(/\.0$/, "")}°`;
    if (st === "none") return { text: `No schedule · holds ${temp(a.temperature)}`, icon: "mdi:alert", cls: "none" };
    if (st === "blocked") return { text: `Schedules can't be read · holds ${temp(a.temperature)}`, icon: "mdi:alert", cls: "none" };
    if (st === "off") return { text: "Scheduling off · you control it", icon: "mdi:account-cog-outline", cls: "mine" };
    if (st === "suspended") return { text: `Suspended · holds ${temp(a.temperature)}`, icon: "mdi:pause", cls: "susp" };
    const o = a.override;
    if (o) {
      const what = o.preset ? name(o.preset) : `Manual ${temp(o.target)}`;
      const until = o.until ? `until ${this._when(o.until)}` : "until you change it";
      return { text: `${what} ${until}${o.keep_when_away ? " · stays when away" : ""}`, icon: "mdi:hand-back-right-outline", cls: "manual" };
    }
    if (a.sun_assist) {
      const pending = a.sun_assist.status === "pending";
      const check = a.sun_assist.check_at ? `, checks ${hhmm(a.sun_assist.check_at)}` : "";
      return { text: pending ? "Sun assist · reading the forecast" : `Sun assist · ${name(a.preset_mode)} waits${check}`, icon: "mdi:white-balance-sunny", cls: "sun" };
    }
    const now = a.preset_mode && a.preset_mode !== "none" ? a.preset_mode : null;
    let text = now ? name(now) : "";
    if (now && now !== "off" && P[now] && P[now].temperature === null) text = `${name(now)} → Off (not used here)`;
    if (a.next_change) text = `${text ? `${text} · ` : ""}${name(a.next_change.preset)} at ${hhmm(a.next_change.at)}`;
    return { text: text || "Schedule", icon: "mdi:clock-outline", cls: "" };
  }

  // Today strip: the schedule's blocks in preset colours, the change by hand
  // (hatched) and the sun assist wait on top, and a now marker.
  _strip(el, a) {
    const blocks = a.schedule_state ? todayBlocks(a.schedule) : [];
    el.classList.toggle("show", blocks.length > 0);
    if (!blocks.length) { el.innerHTML = ""; return; }
    const P = presetMap(a);
    const now = new Date();
    const nowMin = now.getHours() * 60 + now.getMinutes();
    const pct = (m) => `${(Math.max(0, Math.min(1440, m)) / 1440) * 100}%`;
    const box = (from, to, cls, bg = "") => `<i class="${cls}" style="left:${pct(from)};width:${pct(to - from)}${bg ? `;background:${bg}` : ""}"></i>`;
    let html = blocks.map(([from, to, p]) => {
      // A preset the room doesn't use means Off there
      const notUsed = p !== "off" && P[p] && P[p].temperature === null;
      return box(from, to, "blk", esc(notUsed ? P.off.color : (P[p] || P.off).color));
    }).join("");
    const untilMin = (iso) => {
      if (!iso) return 1440;
      const d = new Date(iso);
      return d.toDateString() === now.toDateString() ? d.getHours() * 60 + d.getMinutes() : 1440;
    };
    if (a.override) html += box(nowMin, untilMin(a.override.until), "over");
    else if (a.sun_assist) html += box(nowMin, untilMin(a.sun_assist.check_at), "sunwait");
    html += `<i class="now" style="left:${pct(nowMin)}"></i>`;
    el.innerHTML = html;
  }

  _when(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const today = new Date();
    if (d.toDateString() === today.toDateString()) return hhmm(iso);
    return `${d.toLocaleDateString(undefined, { weekday: "short" })} ${hhmm(iso)}`;
  }

  // The integration's guest mode switch (only there with the Guest mode feature on).
  _guestEntity() {
    const ents = this._hass.entities || {};
    const id = Object.keys(ents).find((k) => k.startsWith("switch.") && ents[k].platform === INTEGRATION && ents[k].translation_key === "guest_mode");
    return id || null;
  }

  // A service call whose refusal (a room without a schedule, say) is shown.
  async _call(domain, service, data) {
    try {
      await this._hass.callService(domain, service, data);
    } catch (err) {
      const ev = new Event("hass-notification", { bubbles: true, composed: true });
      ev.detail = { message: (err && err.message) || String(err) };
      this.dispatchEvent(ev);
    }
  }

  _suspendTap() {
    const anyRoom = this._houseRooms(this._rooms()).find((r) => {
      const s = this._state(r.entity);
      return s && s.attributes.schedule_state !== undefined;
    });
    const susp = !!anyRoom && this._state(anyRoom.entity).attributes.schedules_suspended === true;
    this._call(INTEGRATION, susp ? "resume_schedules" : "suspend_schedules", {});
  }

  // ---------------------------------------------------------------- dialogs
  _openDialog(html, wire) {
    this._closeDialog();
    const d = document.createElement("div");
    d.className = "dlg";
    d.innerHTML = `<div class="dbox" role="dialog" aria-modal="true">${html}</div>`;
    d.addEventListener("click", (ev) => { if (ev.target === d) this._closeDialog(); });
    this.shadowRoot.appendChild(d);
    this._dlg = d;
    const close = d.querySelector(".dclose");
    if (close) close.addEventListener("click", () => this._closeDialog());
    wire(d);
    const first = d.querySelector("input:checked, button.primary");
    if (first && first.focus) first.focus();
  }

  _closeDialog() {
    if (this._dlg) this._dlg.remove();
    this._dlg = null;
  }

  _head(title, sub) {
    return `<div class="dhead"><div><div class="dtitle">${esc(title)}</div><div class="dsub">${esc(sub || "")}</div></div>
      <button class="dclose" aria-label="Close"><ha-icon icon="mdi:close"></ha-icon></button></div>`;
  }

  _opt(name, value, title, small, checked) {
    return `<label class="opt"><input type="radio" name="${name}" value="${esc(value)}"${checked ? " checked" : ""}><span><b>${esc(title)}</b>${small ? `<small>${esc(small)}</small>` : ""}</span></label>`;
  }

  // "Keep this until": a change by hand on a room with a schedule (set_override).
  _targetTap(entityId) {
    const s = this._state(entityId);
    const r = this._rows.get(entityId);
    if (!s || !r) return;
    const a = s.attributes;
    if (!["active", "suspended"].includes(a.schedule_state) || s.state === "off") return;
    const P = presetMap(a);
    const step = Number(r.room.step || this._config.step || a.target_temp_step || 0.5);
    let value = num(r.pending !== null ? r.pending : a.temperature) ?? 20;
    const nc = a.next_change;
    const later = (h) => { const d = new Date(Date.now() + h * 3600e3); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
    const past = (h) => nc && new Date(nc.at) < new Date(Date.now() + h * 3600e3) ? `, past the ${hhmm(nc.at)} change` : "";
    const o = a.override;
    const says = nc ? `Schedule says ${P[a.preset_mode] ? P[a.preset_mode].name : ""} until ${hhmm(nc.at)}` : "Follows its schedule";
    const html = `${this._head(r.room.label, says)}
      <div class="dset"><button class="adj ddown" aria-label="Lower target"><ha-icon icon="mdi:minus"></ha-icon></button>
        <div class="dval"><span class="dv"></span><small>now ${fmt(a.current_temperature)}°</small></div>
        <button class="adj dup" aria-label="Raise target"><ha-icon icon="mdi:plus"></ha-icon></button></div>
      <fieldset><legend>Keep this until</legend>
        ${this._opt("until", "next_change", "Next schedule change", nc ? `${P[nc.preset] ? P[nc.preset].name : nc.preset} at ${hhmm(nc.at)}` : "", !o || !!o.until)}
        ${this._opt("until", "1", "1 hour", `until ${later(1)}${past(1)}`, false)}
        ${this._opt("until", "3", "3 hours", `until ${later(3)}${past(3)}`, false)}
        ${this._opt("until", "permanent", "Until I change it", "schedule off for this room until Back to schedule", !!o && !o.until)}
      </fieldset>
      <label class="opt"><input type="checkbox" class="keep"${o && o.keep_when_away ? " checked" : ""}><span><b>Keep when everyone is away</b>
        <small>Off: this change ends when the house goes away. On: for a visitor Home Assistant doesn't track.</small></span></label>
      <div class="dbtns"><button class="btn back">Back to schedule</button><button class="btn primary set"></button></div>`;
    this._openDialog(html, (d) => {
      const min = a.min_temp ?? 5;
      const max = a.max_temp ?? 30;
      const show = () => {
        d.querySelector(".dv").textContent = `${fmt(value)}°`;
        d.querySelector(".set").textContent = `Set ${fmt(value)}°`;
      };
      const move = (dir) => { value = Math.round(Math.min(max, Math.max(min, value + dir * step)) * 100) / 100; show(); };
      d.querySelector(".ddown").addEventListener("click", () => move(-1));
      d.querySelector(".dup").addEventListener("click", () => move(1));
      d.querySelector(".back").addEventListener("click", () => {
        this._call(INTEGRATION, "resume_schedule", { entity_id: entityId });
        this._closeDialog();
      });
      d.querySelector(".set").addEventListener("click", () => {
        const until = d.querySelector('input[name="until"]:checked').value;
        const data = { entity_id: entityId, temperature: value, keep_when_away: d.querySelector(".keep").checked };
        if (until === "1" || until === "3") data.duration = { hours: Number(until) };
        else data.until = until;
        this._call(INTEGRATION, "set_override", data);
        this._closeDialog();
      });
      show();
    });
  }

  // Make schedule: one preset all day, every day; save is enough (#115).
  _makeDialog(entityId) {
    const s = this._state(entityId);
    const r = this._rows.get(entityId);
    if (!s || !r) return;
    const a = s.attributes;
    const presets = (a.presets || []).filter((p) => p.temperature !== null);
    const html = `${this._head(r.room.label, "Start with one preset all day; change the schedule on the card later.")}
      <fieldset><legend>All day, every day</legend>
        ${presets.map((p, i) => this._opt("preset", p.id, p.name, `${fmt(p.temperature)}°`, p.id === "eco" || (i === 0 && !presets.some((x) => x.id === "eco")))).join("")}
      </fieldset>
      <div class="dbtns"><button class="btn cancel">Cancel</button><button class="btn primary save">Save schedule</button></div>`;
    this._openDialog(html, (d) => {
      d.querySelector(".cancel").addEventListener("click", () => this._closeDialog());
      d.querySelector(".save").addEventListener("click", () => {
        const preset = d.querySelector('input[name="preset"]:checked').value;
        const week = Array.from({ length: 7 }, () => [{ time: "00:00", preset }]);
        this._call(INTEGRATION, "set_schedule", { entity_id: entityId, week });
        this._closeDialog();
      });
    });
  }

  // Guest mode: someone is home, until switched off or a set time (#117).
  _guestDialog() {
    const id = this._guest;
    const gs = this._state(id);
    if (!gs) return;
    const on = gs.state === "on";
    const end = new Date(Date.now() + 24 * 3600e3);
    const local = `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}T${pad(end.getHours())}:00`;
    const html = `${this._head("Someone is home", "For visitors Home Assistant doesn't track. Presence is ignored and every room follows its schedule, as if you were home.")}
      <fieldset><legend>Ends</legend>
        ${this._opt("ends", "off", "Until I turn it off", "stays on when you come home and leave again", true)}
        <label class="opt"><input type="radio" name="ends" value="at"><span><b>At a set time</b><input type="datetime-local" class="at" value="${local}"></span></label>
      </fieldset>
      <div class="dbtns">${on ? `<button class="btn stop">Turn off</button>` : ""}<button class="btn primary start">${on ? "Save" : "Start guest mode"}</button></div>`;
    this._openDialog(html, (d) => {
      const stop = d.querySelector(".stop");
      if (stop) stop.addEventListener("click", () => { this._call(INTEGRATION, "set_guest_mode", { on: false }); this._closeDialog(); });
      d.querySelector(".at").addEventListener("focus", () => { d.querySelector('input[value="at"]').checked = true; });
      d.querySelector(".start").addEventListener("click", () => {
        const data = { on: true };
        if (d.querySelector('input[name="ends"]:checked').value === "at") data.until = new Date(d.querySelector(".at").value).toISOString();
        this._call(INTEGRATION, "set_guest_mode", data);
        this._closeDialog();
      });
    });
  }

  _adjust(entityId, dir) {
    const r = this._rows.get(entityId);
    const s = this._state(entityId);
    if (!r || !s) return;
    const a = s.attributes;
    const step = Number(r.room.step || this._config.step || a.target_temp_step || 0.5);
    const min = a.min_temp ?? 5;
    const max = a.max_temp ?? 30;
    const base = Number(r.pending !== null ? r.pending : (a.temperature ?? min));
    let v = Math.round((base + dir * step) / step) * step;
    v = Math.round(Math.min(max, Math.max(min, v)) * 100) / 100;
    r.pending = v;

    // One service call after the last tap, so the TRVs are written once.
    clearTimeout(r.timer);
    clearTimeout(r.clear);
    r.timer = setTimeout(() => {
      r.timer = null;
      this._hass.callService("climate", "set_temperature", { entity_id: entityId, temperature: v });
      // Fallback if HA never confirms (rejected call, rounding)
      r.clear = setTimeout(() => {
        r.pending = null;
        this._update();
      }, 5000);
      this._update();
    }, 800);
    this._update();
  }

  _modeTap(entityId) {
    const r = this._rows.get(entityId);
    const s = this._state(entityId);
    if (!s) return;
    const modes = s.attributes.hvac_modes || [];
    const onMode = (r && r.room.on_mode) || this._config.on_mode || (modes.includes("heat") ? "heat" : modes.find((m) => m !== "off"));
    this._hass.callService("climate", "set_hvac_mode", {
      entity_id: entityId,
      hvac_mode: s.state === "off" ? onMode : "off",
    });
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId };
    this.dispatchEvent(ev);
  }
}

/* ---------- Visual editor ---------- */

const SCHEMA = [
  { name: "title", selector: { text: {} } },
  { name: "thermostats", selector: { entity: { domain: "climate", multiple: true } } },
  { name: "show_off", selector: { boolean: {} } },
  { name: "boiler", selector: { entity: { domain: "binary_sensor" } } },
  { name: "hot_water", selector: { entity: { domain: "binary_sensor" } } },
  { name: "flame", selector: { entity: { domain: "binary_sensor" } } },
  { name: "modulation", selector: { entity: { domain: "sensor" } } },
  { name: "ch_enabled", selector: { entity: { domain: ["switch", "input_boolean"] } } },
  { name: "pressure", selector: { entity: { domain: "sensor" } } },
  { name: "fault", selector: { entity: { domain: "binary_sensor" } } },
  { name: "water_flow", selector: { entity: { domain: "sensor" } } },
  {
    type: "expandable", name: "colors", title: "Colors", schema: [
      {
        type: "grid", name: "", schema: Object.keys(COLORS).map((k) => ({ name: k, selector: { text: {} } })),
      },
    ],
  },
  {
    type: "grid", name: "", schema: [
      { name: "pressure_min", selector: { number: { min: 0, max: 3, step: 0.1, mode: "box", unit_of_measurement: "bar" } } },
      { name: "pressure_max", selector: { number: { min: 0, max: 4, step: 0.1, mode: "box", unit_of_measurement: "bar" } } },
      { name: "step", selector: { number: { min: 0.1, max: 1, step: 0.1, mode: "box", unit_of_measurement: "°" } } },
    ],
  },
];

const LABELS = {
  title: "Title",
  thermostats: "Rooms (empty: all rooms of Cloudless Multiroom Thermostat)",
  show_off: "Show rooms that are off",
  boiler: "Central heating active",
  hot_water: "Hot water active",
  flame: "Flame on",
  modulation: "Relative modulation level",
  ch_enabled: "Central heating enabled",
  pressure: "CH water pressure",
  fault: "Boiler fault indication",
  water_flow: "Water flow (L/min, optional)",
  pressure_min: "Low pressure threshold",
  pressure_max: "High pressure threshold",
  step: "Setpoint step",
  heating: "Heating",
  hot_water: "Hot water",
  pumping: "Pumping",
  idle: "Idle",
  offline: "Offline",
  fault: "Fault",
  warning: "Pressure warning",
  room: "Rooms in heat",
  water: "Water flow",
  accent: "Accent (buttons, selection)",
  override: "Change by hand",
};

async function loadHaForm() {
  if (customElements.get("ha-form")) return;
  const helpers = await window.loadCardHelpers?.();
  if (!helpers) return;
  const card = await helpers.createCardElement({ type: "entities", entities: [] });
  await card.constructor.getConfigElement();
}

class HeatingControlCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  async connectedCallback() {
    await loadHaForm();
    this._render();
  }

  _render() {
    if (!this._hass || !this._config || !customElements.get("ha-form")) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.schema = SCHEMA;
      this._form.computeLabel = (s) => LABELS[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        const cfg = { ...ev.detail.value };
        if (Array.isArray(cfg.thermostats) && !cfg.thermostats.length) delete cfg.thermostats;
        if (cfg.colors) {
          const col = Object.fromEntries(Object.entries(cfg.colors).filter(([, v]) => v !== "" && v != null));
          if (Object.keys(col).length) cfg.colors = col;
          else delete cfg.colors;
        }
        this._config = cfg;
        this.dispatchEvent(new CustomEvent("config-changed", {
          detail: { config: this._config }, bubbles: true, composed: true,
        }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    // Objects in YAML (entity + name) show as plain entities in the editor.
    const data = { ...this._config };
    if (Array.isArray(data.thermostats)) data.thermostats = data.thermostats.map((t) => (typeof t === "string" ? t : t.entity));
    this._form.data = data;
  }
}

if (!customElements.get("heating-control-card")) {
  customElements.define("heating-control-card", HeatingControlCard);
}
if (!customElements.get("heating-control-card-editor")) {
  customElements.define("heating-control-card-editor", HeatingControlCardEditor);
}

// Once, also when a separately installed copy of the card loaded first.
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "heating-control-card")) window.customCards.push({
  type: "heating-control-card",
  name: "Heating Control Card",
  description: "Every room of Cloudless Multiroom Thermostat, the room the boiler heats for, boiler status and pressure warning.",
  preview: true,
});

console.info(`%c HEATING-CONTROL-CARD %c ${VERSION} `, "background:#ff5722;color:#fff", "");
