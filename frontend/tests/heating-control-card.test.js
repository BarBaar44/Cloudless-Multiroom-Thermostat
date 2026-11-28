// Tests for heating-control-card.js in a simulated browser. Run: npm test
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window;
const CARD = path.join(__dirname, "..", "..", "custom_components", "cloudless_multiroom_thermostat", "www", "heating-control-card.js");
w.eval(fs.readFileSync(CARD, "utf8"));
const Card = w.customElements.get("heating-control-card");
assert(Card, "registered");

const INT = "cloudless_multiroom_thermostat";
const B = {
  boiler: "binary_sensor.main_thermostat_central_heating_active",
  dhw: "binary_sensor.main_thermostat_domestic_hot_water_active",
  flame: "binary_sensor.diyless_thermostat_flame_on",
  mod: "sensor.thermostat_relative_modulation_level",
  ch: "switch.main_thermostat_central_heating_enabled",
  fault: "binary_sensor.main_thermostat_fault_indication",
  pressure: "sensor.thermostat_water_pressure_in_ch_circuit",
};
const st = (state, attributes = {}) => ({ state: String(state), attributes });

/* Boiler entities: mode "idle", "heating", "pumping", "dhw", "dhw_ch", "offline". */
function boiler(mode = "idle", o = {}) {
  const on = (b) => st(b ? "on" : "off");
  const off = mode === "offline";
  return {
    [B.boiler]: off ? st("unavailable") : on(["heating", "pumping", "dhw_ch"].includes(mode)),
    [B.dhw]: on(mode === "dhw" || mode === "dhw_ch"),
    [B.flame]: off ? st("unavailable") : on(["heating", "dhw", "dhw_ch"].includes(mode)),
    [B.mod]: st(o.mod ?? 40),
    [B.ch]: on(o.ch !== false),
    [B.fault]: on(!!o.fault),
    [B.pressure]: st(o.pressure ?? 1.8),
  };
}

/* A room climate. */
function room(name, cur, tgt, attrs = {}, mode = "heat") {
  return st(mode, {
    friendly_name: name, current_temperature: cur, temperature: tgt,
    hvac_modes: ["off", "heat"], min_temp: 5, max_temp: 30, target_temp_step: 0.5, ...attrs,
  });
}

function hass(states, entities = {}) {
  const calls = [];
  return { states, entities, callService: (d, s, data) => calls.push([d, s, data]), calls };
}
/* Integration rooms: every climate in `rooms` gets the integration platform. */
function intHass(rooms, mode = "idle", o = {}) {
  const entities = Object.fromEntries(Object.keys(rooms).map((id) => [id, { entity_id: id, platform: INT }]));
  return hass({ ...boiler(mode, o), ...rooms, ...(o.extra || {}) }, entities);
}

function render(h, config = {}) {
  const c = new Card();
  w.document.body.appendChild(c);
  c.setConfig(config);
  c.hass = h;
  return c;
}
function read(c) {
  const sr = c.shadowRoot;
  const cls = c._el.card.classList;
  return {
    winner: c._el.winner.textContent,
    sub: c._el.sub.textContent,
    icon: c._el.flame.getAttribute("icon"),
    sched: c._el.sched.classList.contains("show"),
    schedText: c._el.sched.textContent.trim(),
    cls: (k) => cls.contains(k),
    rows: [...sr.querySelectorAll(".row")].map((r) => ({
      name: r.querySelector(".rname").textContent,
      role: r.querySelector(".rtext").textContent,
      icon: r.querySelector(".ricon").getAttribute("icon"),
      cls: (k) => r.classList.contains(k),
      down: r.querySelector(".down").disabled,
    })),
  };
}
const row = (v, name) => v.rows.find((r) => r.name === name);

let n = 0;
function test(name, fn) {
  fn();
  n++;
  console.log(`ok ${n} ${name}`);
}

/* ---------------- integration rooms ---------------- */

const HALL = "climate.hallway";
const OFFICE = "climate.office";
const LIVING = "climate.living_room";

test("waiting room alone: header Heating off, row Waiting for heat, no demand", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17.5, 19, { role: "waiting", is_winner: false }),
    [OFFICE]: room("Office", 20.5, 20, { role: "reached", is_winner: false }),
  })));
  assert.strictEqual(v.winner, "Heating off");
  assert.strictEqual(v.sub, "Boiler idle · Hallway waiting");
  assert.strictEqual(v.icon, "mdi:fire-off");
  assert(!v.cls("burning"));
  const h = row(v, "Hallway");
  assert.strictEqual(h.role, "Waiting for heat");
  assert.strictEqual(h.icon, "mdi:timer-sand");
  assert(h.cls("waiting") && !h.cls("win") && !h.cls("along"));
  assert.strictEqual(row(v, "Office").role, "Reached");
});

test("two waiting rooms: count in the sub line", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17.5, 19, { role: "waiting" }),
    [OFFICE]: room("Office", 18, 20, { role: "waiting" }),
  })));
  assert.strictEqual(v.winner, "Heating off");
  assert.strictEqual(v.sub, "Boiler idle · 2 rooms waiting");
});

test("waiting room heats along once another room wins", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17.5, 19, { role: "passenger" }),
    [OFFICE]: room("Office", 18, 20, { role: "winner", is_winner: true, effective_target: 20 }),
  }, "heating")));
  assert.strictEqual(v.winner, "Office");
  assert(v.sub.includes("boiler heating"));
  assert.strictEqual(row(v, "Office").role, "Heating");
  const h = row(v, "Hallway");
  assert.strictEqual(h.role, "Heating along");
  assert(h.cls("along") && !h.cls("waiting"));
});

test("passenger while pumping", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17.5, 19, { role: "passenger" }),
    [OFFICE]: room("Office", 18, 20, { role: "winner", is_winner: true }),
  }, "pumping")));
  assert.strictEqual(row(v, "Office").role, "Pumping");
  assert.strictEqual(row(v, "Hallway").role, "Pumping along");
  assert(!row(v, "Hallway").cls("along"));
});

test("passenger with no boiler activity (switch heat source) still heats along", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17.5, 19, { role: "passenger" }),
    [OFFICE]: room("Office", 18, 20, { role: "winner", is_winner: true }),
  })));
  assert.strictEqual(row(v, "Hallway").role, "Heating along");
});

test("calls_for_heat without a winner: header names it", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17.5, 19, { role: "waiting" }),
    [OFFICE]: room("Office", 18, 20, { role: "calls_for_heat" }),
  })));
  assert.strictEqual(v.winner, "Office calls for heat");
  assert.strictEqual(v.sub, "Boiler idle");
  assert.strictEqual(row(v, "Office").role, "Calls for heat");
  assert.strictEqual(row(v, "Hallway").role, "Waiting for heat");
});

test("role follows the integration, not the card's own target test (eco preset)", () => {
  // Below `temperature`, but at its effective (eco) target: the integration says reached.
  const v = read(render(intHass({
    [OFFICE]: room("Office", 18, 20, { role: "reached", effective_target: 17 }),
  }, "heating")));
  assert.strictEqual(row(v, "Office").role, "Reached");
  assert.strictEqual(v.winner, "All rooms at target");
});

test("no role attribute: card works it out", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17.5, 19),
    [OFFICE]: room("Office", 18, 20, { is_winner: true }),
  }, "heating")));
  assert.strictEqual(row(v, "Office").role, "Heating");
  assert.strictEqual(row(v, "Hallway").role, "Heating along");
  const v2 = read(render(intHass({ [HALL]: room("Hallway", 17.5, 19) })));
  assert.strictEqual(row(v2, "Hallway").role, "Calls for heat");
  assert.strictEqual(v2.winner, "All rooms at target");
});

test("unknown role value falls back to the card's own logic", () => {
  const v = read(render(intHass({ [HALL]: room("Hallway", 20, 19, { role: "something_new" }) })));
  assert.strictEqual(row(v, "Hallway").role, "Reached");
});

test("waiting room with the central heating switch off (the integration did that): same as without it", () => {
  const v = read(render(intHass({ [HALL]: room("Hallway", 17.5, 19, { role: "waiting", drives_heat_source: false }) }, "idle", { ch: false })));
  assert.strictEqual(v.winner, "Heating off");
  assert.strictEqual(v.sub, "Boiler idle · Hallway waiting");
  assert(!v.sched);
});

test("every room paused for away with the switch off: nobody home, no switch note", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17, 19, { role: "paused", paused_reason: "away" }),
    [OFFICE]: room("Office", 18, 20, { role: "paused", paused_reason: "away" }),
  }, "idle", { ch: false })));
  assert.strictEqual(v.winner, "Heating off · nobody home");
  assert(!v.sched);
});

test("window and manual pause with the switch off: Heating paused, no switch note", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17, 19, { role: "paused", paused_reason: "window" }),
    [OFFICE]: room("Office", 17, 20, { role: "paused", paused_reason: "manual" }),
  }, "idle", { ch: false })));
  assert.strictEqual(v.winner, "Heating paused");
  assert(!v.sched);
});

test("a heating room that drives, but the switch is off: Heating off with the switch note", () => {
  const v = read(render(intHass({ [OFFICE]: room("Office", 18, 20, { role: "calls_for_heat", drives_heat_source: true }) }, "idle", { ch: false })));
  assert.strictEqual(v.winner, "Heating off");
  assert(v.sched);
  assert.strictEqual(v.schedText, "Central heating switch is off");
});

test("a room that only heats along and has reached target, switch off: no switch note", () => {
  const v = read(render(intHass({ [HALL]: room("Hallway", 19.5, 19, { role: "reached", drives_heat_source: false }) }, "idle", { ch: false })));
  assert(!v.sched);
});

test("waiting room during hot water: header Hot water", () => {
  const v = read(render(intHass({ [HALL]: room("Hallway", 17.5, 19, { role: "waiting" }) }, "dhw")));
  assert.strictEqual(v.winner, "Hot water");
  assert.strictEqual(v.icon, "mdi:shower-head");
  assert.strictEqual(row(v, "Hallway").role, "Waiting for heat");
});

test("pauses keep their texts, rows editable; all away", () => {
  const v = read(render(intHass({
    [HALL]: room("Hallway", 17, 19, { role: "paused", paused_reason: "window" }),
    [OFFICE]: room("Office", 17, 20, { role: "paused", paused_reason: "manual" }),
  })));
  assert.strictEqual(row(v, "Hallway").role, "Paused · window open");
  assert(!row(v, "Hallway").cls("away"));
  assert.strictEqual(row(v, "Office").role, "Paused");
  assert(!row(v, "Hallway").down);
  assert.strictEqual(v.winner, "Heating paused");
  const v2 = read(render(intHass({ [HALL]: room("Hallway", 17, 19, { role: "paused", paused_reason: "away" }) })));
  assert.strictEqual(v2.winner, "Heating off · nobody home");
  const h2 = row(v2, "Hallway");
  assert.strictEqual(h2.role, "Away");
  assert(h2.cls("away") && h2.cls("paused"));
});

test("off room shows Off; only integration climates listed, named after the room", () => {
  const h = intHass({ [HALL]: room("Hallway", 17, 19, { role: "off" }, "off") });
  h.states["climate.virtual_thermostat_attic"] = room("Attic", 15, 18);
  const v = read(render(h));
  assert.deepStrictEqual(v.rows.map((r) => r.name), ["Hallway"]);
  assert.strictEqual(v.rows[0].role, "Off");
  assert.strictEqual(v.winner, "Heating off");
});

test("thermostats list: header speaks for the whole house, rows stay the listed rooms", () => {
  const BED = "climate.master_bedroom";
  const rooms = {
    [LIVING]: room("Living Room", 19.2, 10, { role: "off", is_winner: false }, "off"),
    [BED]: room("Master Bedroom", 16.6, 21, { role: "winner", is_winner: true, effective_target: 21 }),
  };
  const c = render(intHass(rooms, "heating", { mod: 30 }), { thermostats: [LIVING] });
  const v = read(c);
  assert.deepStrictEqual(v.rows.map((r) => r.name), ["Living Room"]);
  assert.strictEqual(v.rows[0].role, "Off");
  assert.strictEqual(v.winner, "Master Bedroom");
  assert.strictEqual(v.sub, "16.6° → 21.0° · boiler heating · 30%");
  assert.strictEqual(v.icon, "mdi:fire");
  assert(v.cls("single"));
  assert.strictEqual(c._winnerEntity, BED);
  // A room that is not listed calls for heat or waits: the header names it too.
  rooms[BED] = room("Master Bedroom", 16.6, 21, { role: "calls_for_heat", is_winner: false });
  assert.strictEqual(read(render(intHass(rooms), { thermostats: [LIVING] })).winner, "Master Bedroom calls for heat");
  rooms[BED] = room("Master Bedroom", 16.6, 21, { role: "waiting", is_winner: false });
  const v3 = read(render(intHass(rooms), { thermostats: [LIVING] }));
  assert.strictEqual(v3.winner, "Heating off");
  assert.strictEqual(v3.sub, "Boiler idle · Master Bedroom waiting");
  // Everything off: still Heating off.
  rooms[BED] = room("Master Bedroom", 16.6, 21, { role: "off", is_winner: false }, "off");
  assert.strictEqual(read(render(intHass(rooms), { thermostats: [LIVING] })).winner, "Heating off");
});

/* ---------------- boiler states ---------------- */

const twoRooms = (o = {}) => ({
  [LIVING]: room("Living Room", 19, 21, { role: o.win ? "winner" : "calls_for_heat", is_winner: !!o.win, effective_target: 21 }),
  [OFFICE]: room("Office", 20.5, 20, { role: "reached" }),
});

test("heating winner and reached room", () => {
  const v = read(render(intHass(twoRooms({ win: true }), "heating")));
  assert.strictEqual(v.winner, "Living Room");
  assert(v.sub.includes("boiler heating · 40%"));
  assert.strictEqual(v.icon, "mdi:fire");
  assert(v.cls("burning"));
  assert.strictEqual(row(v, "Living Room").role, "Heating");
  assert.strictEqual(row(v, "Office").role, "Reached");
});

test("pumping winner", () => {
  assert.strictEqual(row(read(render(intHass(twoRooms({ win: true }), "pumping"))), "Living Room").role, "Pumping");
});

test("hot water + CH, offline, fault, pressure, schedule off", () => {
  assert.strictEqual(read(render(intHass(twoRooms(), "dhw_ch"))).winner, "Hot water");
  const off = read(render(intHass(twoRooms({ win: true }), "offline")));
  assert.strictEqual(off.winner, "Thermostat offline");
  assert.strictEqual(off.icon, "mdi:lan-disconnect");
  const f = read(render(intHass(twoRooms(), "idle", { fault: true })));
  assert.strictEqual(f.winner, "Boiler fault");
  assert(f.cls("fault"));
  assert.strictEqual(read(render(intHass(twoRooms(), "idle", { pressure: 1.1 }))).icon, "mdi:fire-alert");
  assert(read(render(intHass(twoRooms(), "idle", { pressure: 2.9 }))).cls("alert"));
  assert.strictEqual(read(render(intHass(twoRooms(), "idle", { ch: false }))).winner, "Heating off");
});

test("explicit list with a name; old YAML keys are ignored", () => {
  const v = read(render(intHass(twoRooms()), { thermostats: [{ entity: OFFICE, name: "Work" }] }));
  assert.deepStrictEqual(v.rows.map((r) => r.name), ["Work"]);
  assert(v.cls("single"));
  const v2 = read(render(intHass(twoRooms()), { climate: "climate.virtual_thermostat_living_room", heating_area: "sensor.delta_temperature" }));
  assert.deepStrictEqual(v2.rows.map((r) => r.name), ["Living Room", "Office"]);
});

test("setpoint taps send one batched call", async () => {
  const h = intHass(twoRooms());
  const c = render(h, { thermostats: [LIVING] });
  const up = c.shadowRoot.querySelector(".row .up");
  up.click(); up.click(); up.click();
  return new Promise((res) => setTimeout(() => {
    const sets = h.calls.filter(([, s]) => s === "set_temperature");
    assert.strictEqual(sets.length, 1);
    assert.strictEqual(sets[0][2].temperature, 22.5);
    res();
  }, 900));
});

/* ---------------- v2 schedules ---------------- */

// Objects made inside the simulated window come from another realm: compare as JSON.
const same = (a, b) => assert.strictEqual(JSON.stringify(a), JSON.stringify(b));

const PRESETS = (warm = 19, sleep = null) => [
  { id: "eco", name: "Eco", color: null, temperature: 15 },
  { id: "warm", name: "Warm", color: "#ff5722", temperature: warm },
  { id: "sleep", name: "Sleep", color: null, temperature: sleep },
];
const WEEK = Array.from({ length: 7 }, () => [{ time: "07:00", preset: "warm" }, { time: "22:00", preset: "eco" }]);
const todayAt = (h, m = 0) => { const d = new Date(); d.setHours(h, m, 0, 0); return d.toISOString(); };
const sched = (o = {}) => ({
  schedule_state: "active", schedule: WEEK, schedules_suspended: false, presets: PRESETS(),
  preset_mode: "warm", next_change: { at: todayAt(22), preset: "eco" }, override: null, sun_assist: null, ...o,
});
const schedLine = (c, name) => {
  const r = [...c.shadowRoot.querySelectorAll(".row")].find((x) => x.querySelector(".rname").textContent === name);
  return { el: r, text: r.querySelector(".stext").textContent, cls: r.querySelector(".rsched").className };
};

test("schedule line: preset now and the next change", () => {
  const c = render(intHass({ [LIVING]: room("Living Room", 20, 19, sched()) }));
  assert.strictEqual(schedLine(c, "Living Room").text, "Warm · Eco at 22:00");
  assert(schedLine(c, "Living Room").el.querySelector(".strip").classList.contains("show"));
  assert.strictEqual(schedLine(c, "Living Room").el.querySelectorAll(".strip .blk").length, 3);
});

test("schedule line: change by hand, kept when away, and until you change it", () => {
  const c = render(intHass({
    [LIVING]: room("Living Room", 20, 21, sched({ override: { target: 21, preset: null, until: todayAt(17), keep_when_away: true } })),
    [OFFICE]: room("Office", 19, 15, sched({ override: { target: 15, preset: "eco", until: null, keep_when_away: false } })),
  }));
  assert.strictEqual(schedLine(c, "Living Room").text, "Manual 21° until 17:00 · stays when away");
  assert(schedLine(c, "Living Room").cls.includes("manual"));
  assert.strictEqual(schedLine(c, "Office").text, "Eco until you change it");
  assert(schedLine(c, "Living Room").el.querySelector(".strip .over"));
});

test("schedule line: sun assist, scheduling off, suspended, a preset not used", () => {
  const c = render(intHass({
    [LIVING]: room("Living Room", 16, 15, sched({ sun_assist: { status: "holding", hold: 15, check_at: todayAt(8) } })),
    [OFFICE]: room("Office", 19, 19, sched({ schedule_state: "off", schedule: null })),
    [HALL]: room("Hallway", 17, 15, sched({ schedule_state: "suspended" })),
    "climate.gijs": room("Gijs", 17, 10, sched({ preset_mode: "sleep", next_change: { at: todayAt(7), preset: "warm" } })),
  }));
  assert.strictEqual(schedLine(c, "Living Room").text, "Sun assist · Warm waits, checks 08:00");
  assert.strictEqual(schedLine(c, "Office").text, "Scheduling off · you control it");
  assert.strictEqual(schedLine(c, "Hallway").text, "Suspended · holds 15°");
  assert.strictEqual(schedLine(c, "Gijs").text, "Sleep → Off (not used here) · Warm at 07:00");
});

test("v1 rooms (no schedule attributes) show no schedule line or pills", () => {
  const c = render(intHass({ [LIVING]: room("Living Room", 20, 19) }));
  assert(!schedLine(c, "Living Room").cls.includes("show"));
  assert.strictEqual(c._el.pills.style.display, "none");
});

test("room without a schedule: hatched, locked, two ways out, header count", async () => {
  const h = intHass({
    [HALL]: room("Hallway", 14.8, 15, sched({ schedule_state: "none", schedule: null, preset_mode: "none", next_change: null })),
    [LIVING]: room("Living Room", 20, 19, sched()),
  });
  const c = render(h);
  const r = schedLine(c, "Hallway");
  assert.strictEqual(r.text, "No schedule · holds 15°");
  assert(r.el.classList.contains("nosched"));
  assert(r.el.querySelector(".up").disabled && r.el.querySelector(".down").disabled);
  assert(c._el.nosched.classList.contains("show"));
  assert.strictEqual(c._el.noschedText.textContent, "1 room without a schedule · holds 15°");
  r.el.querySelector(".mine").click();
  same(h.calls.pop(), [INT, "set_schedule", { entity_id: HALL, scheduling: "off" }]);
  r.el.querySelector(".make").click();
  const d = c.shadowRoot.querySelector(".dlg");
  assert(!d.querySelector('input[name="preset"]'), "no picker: the default week (2.0.1)");
  d.querySelector(".save").click();
  await new Promise((r) => setTimeout(r, 0));
  const [, svc, data] = h.calls.pop();
  assert.strictEqual(svc, "set_schedule");
  assert.strictEqual(data.week.length, 7);
  same(data.week[3], [{ time: "00:00", preset: "eco" }, { time: "07:00", preset: "warm" }, { time: "22:00", preset: "eco" }]);
  assert(!c.shadowRoot.querySelector(".dlg"), "dialog closes");
});

test("banner lists rooms without a schedule that the card doesn't show (2.0.1)", async () => {
  const h = intHass({
    [HALL]: room("Hallway", 14.8, 15, sched({ schedule_state: "none", schedule: null, preset_mode: "none", next_change: null })),
    [OFFICE]: room("Office", 14.8, 15, sched({ schedule_state: "none", schedule: null, preset_mode: "none", next_change: null })),
    [LIVING]: room("Living Room", 20, 19, sched()),
  });
  const c = render(h, { thermostats: [LIVING] });
  assert.strictEqual(c._el.noschedText.textContent, "2 rooms without a schedule · holds 15°");
  c._el.nosched.click();
  const d = c.shadowRoot.querySelector(".dlg");
  assert.strictEqual(d.querySelectorAll(".make").length, 2);
  d.querySelector(`.mine[data-e="${HALL}"]`).click();
  same(h.calls.pop(), [INT, "set_schedule", { entity_id: HALL, scheduling: "off" }]);
  c.shadowRoot.querySelector(`.dlg .make[data-e="${OFFICE}"]`).click();
  assert(c.shadowRoot.querySelector(".dlg .dtitle").textContent.includes("Office"));
  c.shadowRoot.querySelector(".dlg .save").click();
  await new Promise((r) => setTimeout(r, 0));
  const [, svc, data] = h.calls.pop();
  assert.strictEqual(svc, "set_schedule");
  assert.strictEqual(data.entity_id, OFFICE);
});

test("today: tap a room to open its schedule (2.0.1)", () => {
  const h = intHass({
    [LIVING]: room("Living Room", 20, 19, sched()),
    [OFFICE]: room("Office", 19, 19, sched()),
  });
  const c = render(h);
  c._view = "today";
  c._update();
  c.shadowRoot.querySelector(`.tlane[data-e="${OFFICE}"]`).click();
  assert.strictEqual(c._ed.entity, OFFICE);
  assert.strictEqual(c._ed.sel[0], (new Date().getDay() + 6) % 7);
});

// Week grid pointer helpers: a bar 1440 px wide, so clientX is the minute.
const edBar = (c, day) => {
  const bar = c.shadowRoot.querySelectorAll(".dlg .bar.ed")[day];
  bar.getBoundingClientRect = () => ({ left: 0, width: 1440, top: 0, height: 38 });
  return bar;
};
const ptr = (el, type, x, y = 0) => el.dispatchEvent(new w.MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 }));
// Every lane 1440 px wide and 40 px high, Monday at the top
const allBars = (c) => [...c.shadowRoot.querySelectorAll(".dlg .bar.ed")].map((b, d) => {
  b.getBoundingClientRect = () => ({ left: 0, width: 1440, top: d * 40, height: 38 });
  return b;
});
const tapBar = (c, day, x) => { const b = edBar(c, day); ptr(b, "pointerdown", x); ptr(b, "pointerup", x); };
const dragBar = (c, day, from, to) => { const b = edBar(c, day); ptr(b, "pointerdown", from); ptr(b, "pointermove", (from + to) / 2); ptr(b, "pointermove", to); ptr(b, "pointerup", to); };

const pickRoom = (c, id) => {
  const sel = c.shadowRoot.querySelector(".dlg .edroom");
  sel.value = id;
  sel.dispatchEvent(new w.Event("change"));
};

test("editor: room dropdown, asks first when there are unsaved changes (2.0.1, 2.0.2)", async () => {
  const h = intHass({
    [LIVING]: room("Living Room", 20, 19, sched()),
    [OFFICE]: room("Office", 19, 19, sched()),
  });
  const c = render(h);
  c._editor(LIVING, 0);
  pickRoom(c, OFFICE);
  assert.strictEqual(c._ed.entity, OFFICE, "nothing changed: switches straight away");
  c._ed.sel = [0, 1];
  c._renderWide();
  c.shadowRoot.querySelector('.trow .adj[data-t="0"][data-d="1"]').click();
  pickRoom(c, LIVING);
  assert.strictEqual(c._ed.entity, OFFICE, "unsaved: stays and asks");
  assert.strictEqual(c.shadowRoot.querySelector(".dlg .edroom").value, OFFICE);
  c.shadowRoot.querySelector(".swsave").click();
  await new Promise((r) => setTimeout(r, 0));
  const data = lastSchedule(h);
  assert.strictEqual(data.entity_id, OFFICE);
  same(data.week[0][1], { time: "07:15", preset: "warm" });
  assert.strictEqual(c._ed.entity, LIVING);
});

test("editor: dropdown lists rooms with scheduling off or no schedule, also unlisted ones (2.0.2)", async () => {
  const h = intHass({
    [LIVING]: room("Living Room", 20, 19, sched()),
    [OFFICE]: room("Office", 19, 19, sched({ schedule_state: "off", schedule: null })),
    [HALL]: room("Hallway", 14.8, 15, sched({ schedule_state: "none", schedule: null })),
  });
  const c = render(h, { thermostats: [LIVING] });
  c._editor(LIVING, 0);
  const opts = [...c.shadowRoot.querySelectorAll(".dlg .edroom option")].map((o) => o.textContent);
  same(opts, ["Living Room", "Office · scheduling off", "Hallway · no schedule"]);
  pickRoom(c, OFFICE);
  assert.strictEqual(c._ed.entity, OFFICE);
  assert(c.shadowRoot.querySelector(".dlg").textContent.includes("this is the default week"));
  c.shadowRoot.querySelector(".dlg .save").click();
  await new Promise((r) => setTimeout(r, 0));
  const data = lastSchedule(h);
  assert.strictEqual(data.entity_id, OFFICE);
  same(data.week[2], [{ time: "00:00", preset: "eco" }, { time: "07:00", preset: "warm" }, { time: "22:00", preset: "eco" }]);
});

test("wide editor: copy day to, tap the day again to undo the copy (2.0.2)", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 0);
  c._ed.days[6] = [[0, 1440, "eco"]];
  c._ed.days[0] = [[0, 1440, "warm"]];
  c._ed.sel = [0, 0];
  c._renderWide();
  c.shadowRoot.querySelector(".copyday").click();
  c.shadowRoot.querySelector('[data-also="6"]').click();
  same(c._ed.days[6], [[0, 1440, "warm"]]);
  assert(c.shadowRoot.querySelector('[data-also="6"]').classList.contains("pick"));
  c.shadowRoot.querySelector('[data-also="6"]').click();
  same(c._ed.days[6], [[0, 1440, "eco"]], "back to what Sunday had");
  assert(!c.shadowRoot.querySelector('[data-also="6"]').classList.contains("pick"));
});

test("a room that doesn't drive the heat source is labelled heats along only (2.0.2)", () => {
  const h = intHass({
    [LIVING]: room("Living Room", 20, 19, sched({ drives_heat_source: true })),
    [HALL]: room("Hallway", 17, 18, sched({ drives_heat_source: false })),
  });
  const c = render(h);
  c._editor(HALL, 0);
  assert(c.shadowRoot.querySelector(".dlg .along").textContent.includes("never starts the boiler"));
  const opts = [...c.shadowRoot.querySelectorAll(".dlg .edroom option")].map((o) => o.textContent);
  assert(opts.includes("Hallway · heats along only") && opts.includes("Living Room"));
  c._editor(LIVING, 0);
  assert(!c.shadowRoot.querySelector(".dlg .along"));
  c._closeDialog();
  c._weekRoom = HALL;
  c._view = "week";
  c._update();
  assert(c._el.weekv.querySelector(".along"));
});

test("week grid: drag a switch point, drag a block, tap twice to split (2.0.3)", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 0);
  same(c._ed.days[0], [[0, 420, "eco"], [420, 1320, "warm"], [1320, 1440, "eco"]]);
  // Every switch point has a grip, also on days that are not selected
  assert.strictEqual(c.shadowRoot.querySelectorAll(".dlg .bar.ed")[3].querySelectorAll(".g").length, 2);
  // Press near 07:00 (within 16 px) and drag: the switch point moves, snapped
  dragBar(c, 0, 425, 482);
  same(c._ed.days[0], [[0, 480, "eco"], [480, 1320, "warm"], [1320, 1440, "eco"]]);
  // Press in the middle of Warm and drag: the whole block moves an hour later
  dragBar(c, 0, 900, 960);
  same(c._ed.days[0], [[0, 540, "eco"], [540, 1380, "warm"], [1380, 1440, "eco"]]);
  // A switch point dragged onto the next one removes the block in between
  dragBar(c, 0, 1380, 1440);
  same(c._ed.days[0], [[0, 540, "eco"], [540, 1440, "warm"]]);
  // Tap selects, a second tap on the same block splits it there
  tapBar(c, 1, 900);
  same(c._ed.sel, [1, 1]);
  tapBar(c, 1, 900);
  same(c._ed.days[1], [[0, 420, "eco"], [420, 900, "warm"], [900, 1440, "eco"]]); // the Eco half joins the Eco after it
});

test("week grid: paint by dragging, down over more days (2.0.3)", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 0);
  c.shadowRoot.querySelector('[data-tool="off"]').click();
  assert(c.shadowRoot.querySelector(".dlg").textContent.includes("Painting Off"));
  // Monday 12:00 to 14:00, dragged down to Wednesday
  const bars = allBars(c);
  ptr(bars[0], "pointerdown", 720, 19);
  ptr(bars[0], "pointermove", 800, 60);
  ptr(bars[0], "pointermove", 840, 99);
  ptr(bars[0], "pointerup", 840, 99);
  for (const d of [0, 1, 2]) same(c._ed.days[d], [[0, 420, "eco"], [420, 720, "warm"], [720, 840, "off"], [840, 1320, "warm"], [1320, 1440, "eco"]]);
  same(c._ed.days[3], [[0, 420, "eco"], [420, 1320, "warm"], [1320, 1440, "eco"]]);
  assert.strictEqual(c._ed.tool, null, "one stroke per tap on a preset");
  // Dragging right to left paints too
  c.shadowRoot.querySelector('[data-tool="warm"]').click();
  dragBar(c, 6, 1440, 1320);
  same(c._ed.days[6], [[0, 420, "eco"], [420, 1440, "warm"]]);
});

test("week grid: drag a day's name onto other days to copy it (2.0.3)", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 0);
  c._ed.days[0] = [[0, 1440, "warm"]];
  c._renderWide();
  [...c.shadowRoot.querySelectorAll(".dlg .lane")].forEach((l, d) => { l.getBoundingClientRect = () => ({ left: 0, width: 1500, top: d * 40, height: 38 }); });
  const lab = c.shadowRoot.querySelector('.dlg .dl[data-d="0"]');
  ptr(lab, "pointerdown", 10, 19);
  ptr(lab, "pointermove", 10, 100);
  ptr(lab, "pointermove", 10, 179);
  ptr(lab, "pointerup", 10, 179);
  for (const d of [1, 2, 3, 4]) same(c._ed.days[d], [[0, 1440, "warm"]]);
  same(c._ed.days[5], [[0, 420, "eco"], [420, 1320, "warm"], [1320, 1440, "eco"]]);
  // A tap on a day's name selects that day
  const sat = c.shadowRoot.querySelector('.dlg .dl[data-d="5"]');
  ptr(sat, "pointerdown", 10, 219);
  ptr(sat, "pointerup", 10, 219);
  same(c._ed.sel, [5, 0]);
});

test("week grid: moving the first block hands its time to the next one", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 0);
  dragBar(c, 0, 200, 260);
  same(c._ed.days[0], [[0, 60, "warm"], [60, 480, "eco"], [480, 1320, "warm"], [1320, 1440, "eco"]]);
});

test("editor: split a whole day block, tool off after one block, drag to midnight (2.0.1)", () => {
  const allDay = Array.from({ length: 7 }, () => [{ time: "00:00", preset: "warm" }]);
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched({ schedule: allDay })) });
  const c = render(h);
  c._editor(LIVING, 0);
  assert(!c.shadowRoot.querySelector(".trow"), "no steppers that can't move");
  c.shadowRoot.querySelector(".split").click();
  same(c._ed.days[0], [[0, 720, "warm"], [720, 1440, "eco"]]);
  assert(c.shadowRoot.querySelectorAll(".dlg .bar.ed")[0].querySelectorAll(".g").length === 1, "a switch point to drag");
  c.shadowRoot.querySelector('[data-tool="off"]').click();
  tapBar(c, 1, 0);
  assert.strictEqual(c._ed.tool, null);
  // The Warm block's end dragged all the way: the Eco block goes, Warm runs to 24:00
  c._ed.sel = [0, 0];
  c._shift(1, 0, 1440);
  c._renderWide();
  same(c._ed.days[0], [[0, 1440, "warm"]]);
});

test("tap the target: Keep this until sends set_override", () => {
  const h = intHass({ [LIVING]: room("Living Room", 18.7, 19, sched()) });
  const c = render(h);
  c.shadowRoot.querySelector(".row .rtgt").click();
  const d = c.shadowRoot.querySelector(".dlg");
  assert(d.querySelector('input[value="next_change"]').checked);
  d.querySelector(".dup").click(); d.querySelector(".dup").click();
  d.querySelector('input[value="3"]').checked = true;
  d.querySelector(".keep").checked = true;
  d.querySelector(".set").click();
  same(h.calls.pop(), [INT, "set_override", { entity_id: LIVING, temperature: 20, keep_when_away: true, duration: { hours: 3 } }]);
  c.shadowRoot.querySelector(".row .rtgt").click();
  c.shadowRoot.querySelector('.dlg input[value="permanent"]').checked = true;
  c.shadowRoot.querySelector(".dlg .set").click();
  assert.strictEqual(h.calls.pop()[2].until, "permanent");
  c.shadowRoot.querySelector(".row .rtgt").click();
  c.shadowRoot.querySelector(".dlg .back").click();
  same(h.calls.pop(), [INT, "resume_schedule", { entity_id: LIVING }]);
});

test("schedule pill suspends and resumes", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  assert.strictEqual(c._el.spillText.textContent, "Schedule");
  c._el.spill.click();
  same(h.calls.pop(), [INT, "suspend_schedules", {}]);
  h.states[LIVING] = room("Living Room", 20, 15, sched({ schedule_state: "suspended", schedules_suspended: true }));
  c.hass = h;
  assert.strictEqual(c._el.spillText.textContent, "Suspended");
  c._el.spill.click();
  same(h.calls.pop(), [INT, "resume_schedules", {}]);
});

test("guest pill only with the guest switch; dialog starts and stops it", () => {
  const GUEST = "switch.heating_someone_is_home_guest_mode";
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) }, "idle", { extra: { [GUEST]: st("off", { until: null }) } });
  const c0 = render(h);
  assert.strictEqual(c0._el.gpill.style.display, "none", "not an integration entity yet");
  h.entities[GUEST] = { entity_id: GUEST, platform: INT, translation_key: "guest_mode" };
  const c = render(h);
  assert.strictEqual(c._el.gpill.style.display, "");
  c._el.gpill.click();
  c.shadowRoot.querySelector(".dlg .start").click();
  same(h.calls.pop(), [INT, "set_guest_mode", { on: true }]);
  h.states[GUEST] = st("on", { until: todayAt(23) });
  c.hass = h;
  assert.strictEqual(c._el.gpillText.textContent, "Guest · until 23:00");
  c._el.gpill.click();
  c.shadowRoot.querySelector(".dlg .stop").click();
  same(h.calls.pop(), [INT, "set_guest_mode", { on: false }]);
});

test("accent and override colours are configurable", () => {
  const c = render(intHass({ [LIVING]: room("Living Room", 20, 19, sched()) }), { colors: { accent: "#3366ff", override: "teal" } });
  assert.strictEqual(c.style.getPropertyValue("--hc-accent"), "#3366ff");
  assert.strictEqual(c.style.getPropertyValue("--hc-override"), "teal");
});

test("a refused call shows its message", async () => {
  const h = intHass({ [HALL]: room("Hallway", 15, 15, sched({ schedule_state: "none" })) });
  h.callService = () => Promise.reject(new Error("Hallway has no schedule: make one or turn scheduling off"));
  const c = render(h);
  let msg = null;
  c.addEventListener("hass-notification", (ev) => { msg = ev.detail.message; });
  await c._call(INT, "set_schedule", { entity_id: HALL, scheduling: "off" });
  assert.strictEqual(msg, "Hallway has no schedule: make one or turn scheduling off");
});

/* ---------------- v2 editor ---------------- */

const lastSchedule = (h) => {
  const c = [...h.calls].reverse().find(([, s]) => s === "set_schedule");
  return c && JSON.parse(JSON.stringify(c[2]));
};

test("week view: tabs, seven lanes, a lane opens the editor", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()), [OFFICE]: room("Office", 19, 19, sched()) });
  const c = render(h);
  assert.notStrictEqual(c._el.tabs.style.display, "none");
  c.shadowRoot.querySelector('.tab[data-v="week"]').click();
  assert.strictEqual(c._el.rooms.style.display, "none");
  assert.strictEqual(c._el.weekv.querySelectorAll(".lane").length, 7);
  assert.strictEqual(c._el.weekv.querySelectorAll(".lane")[0].querySelectorAll(".bar b").length, 3);
  c._el.weekv.querySelectorAll(".lane")[2].click();
  assert(c.shadowRoot.querySelector(".dlg .edgrid"), "wide editor");
  assert(c.shadowRoot.querySelector(".dlg .panel .dtitle").textContent.startsWith("Wed"));
});

test("wide editor: move a switch point by 15 minutes, change a preset, save", async () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 0);
  // Select the Warm block (07:00 to 22:00) through the editor state, then step its start
  c._ed.sel = [0, 1];
  c._renderWide();
  c.shadowRoot.querySelector('.trow .adj[data-t="0"][data-d="1"]').click();
  assert(c.shadowRoot.querySelector(".panel .dtitle").textContent.includes("07:15 to 22:00"));
  c.shadowRoot.querySelector('.choice[data-p="sleep"]').click();
  c.shadowRoot.querySelector(".save").click();
  await new Promise((r) => setTimeout(r, 0));
  const data = lastSchedule(h);
  same(data.week[0], [{ time: "00:00", preset: "eco" }, { time: "07:15", preset: "sleep" }, { time: "22:00", preset: "eco" }]);
  same(data.week[1], [{ time: "00:00", preset: "eco" }, { time: "07:00", preset: "warm" }, { time: "22:00", preset: "eco" }]);
  assert(!c.shadowRoot.querySelector(".dlg"), "closes after saving");
});

test("wide editor: palette paints a block, copy day, remove block", async () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 0);
  c.shadowRoot.querySelector('[data-tool="off"]').click();
  tapBar(c, 0, 0);
  assert.strictEqual(c._ed.days[0][0][2], "off");
  c.shadowRoot.querySelector(".copyday").click();
  c.shadowRoot.querySelector('[data-also="6"]').click();
  same(c._ed.days[6], c._ed.days[0]);
  c._ed.sel = [0, 0];
  c._renderWide();
  assert(c.shadowRoot.querySelector(".rmblock").disabled === false);
  c.shadowRoot.querySelector(".save").click();
  await new Promise((r) => setTimeout(r, 0));
  same(lastSchedule(h).week[6][0], { time: "00:00", preset: "off" });
});

test("more than 12 switch points on a day can't be saved", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 0);
  c._ed.days[0] = Array.from({ length: 13 }, (_, i) => [i * 60, i === 12 ? 1440 : (i + 1) * 60, i % 2 ? "warm" : "eco"]);
  c._renderWide();
  assert(c.shadowRoot.querySelector(".save").disabled);
  assert(c.shadowRoot.querySelector(".warnline").textContent.includes("Mon"));
});

test("phone: one day as a list, also for other days", async () => {
  const before = w.innerWidth;
  w.innerWidth = 400;
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c._editor(LIVING, 5);
  w.innerWidth = before; // the other tests run on a wide screen
  {
    const d = c.shadowRoot.querySelector(".dlg");
    assert(!d.querySelector(".edgrid"), "list, not the grid");
    assert.strictEqual(d.querySelectorAll(".pt").length, 3);
    const sel = d.querySelectorAll(".pt select")[1];
    sel.value = "sleep";
    sel.dispatchEvent(new w.Event("change"));
    c.shadowRoot.querySelector('[data-also="6"]').click();
    assert(c.shadowRoot.querySelector(".save").textContent.includes("Sat + Sun"));
    const t = c.shadowRoot.querySelectorAll(".pt input")[1];
    t.value = "08:10";
    t.dispatchEvent(new w.Event("change"));
    c.shadowRoot.querySelector(".save").click();
    await new Promise((r) => setTimeout(r, 0));
    const week = lastSchedule(h).week;
    same(week[5], [{ time: "00:00", preset: "eco" }, { time: "08:15", preset: "sleep" }, { time: "22:00", preset: "eco" }]);
    same(week[6], week[5]);
  }
});

test("copy to rooms warns about presets the other room doesn't use", async () => {
  const sleepWeek = Array.from({ length: 7 }, () => [{ time: "07:00", preset: "warm" }, { time: "22:00", preset: "sleep" }]);
  const h = intHass({
    [LIVING]: room("Living Room", 20, 19, sched({ schedule: sleepWeek, presets: PRESETS(19, 16) })),
    [OFFICE]: room("Office", 19, 19, sched({ presets: PRESETS(19, null) })),
  });
  const c = render(h);
  c._copyDialog(LIVING);
  c.shadowRoot.querySelector(`.dlg [data-e="${OFFICE}"]`).click();
  assert(c.shadowRoot.querySelector(".warnline").textContent.includes("Office doesn't use Sleep"));
  assert.strictEqual(c.shadowRoot.querySelector(".go").textContent, "Copy anyway");
  c.shadowRoot.querySelector(".go").click();
  await new Promise((r) => setTimeout(r, 0));
  const data = lastSchedule(h);
  assert.strictEqual(data.entity_id, OFFICE);
  same(data.week, sleepWeek);
});

test("the schedule line opens the editor", () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()) });
  const c = render(h);
  c.shadowRoot.querySelector(".row .rsched").click();
  assert(c.shadowRoot.querySelector(".dlg .edgrid"));
});

/* ---------------- v2 today and presets ---------------- */

test("today view: every room on one timeline, coming up grouped", () => {
  const later = Array.from({ length: 7 }, () => [{ time: "00:00", preset: "eco" }, { time: "23:45", preset: "warm" }]);
  const h = intHass({
    [LIVING]: room("Living Room", 20, 15, sched({ schedule: later })),
    [OFFICE]: room("Office", 19, 15, sched({ schedule: later })),
    [HALL]: room("Hallway", 15, 15, sched({ schedule_state: "none", schedule: null })),
  });
  const c = render(h);
  c.shadowRoot.querySelector('.tab[data-v="today"]').click();
  const v = c._el.todayv;
  assert.strictEqual(v.querySelectorAll(".tlane").length, 3);
  assert(v.querySelector(".nosch").textContent.startsWith("No schedule"));
  const items = [...v.querySelectorAll(".citem")].map((x) => x.textContent);
  if (new Date().getHours() * 60 + new Date().getMinutes() < 23 * 60 + 45) {
    assert.strictEqual(items.length, 1, "two rooms at the same time and preset share a line");
    assert(items[0].includes("Living Room, Office") && items[0].includes("Eco → Warm 19.0°"));
  }
});

test("presets dialog: change a temperature, add a preset, not used, save in one call", async () => {
  const h = intHass({ [LIVING]: room("Living Room", 20, 19, sched()), [OFFICE]: room("Office", 19, 19, sched()) });
  const c = render(h);
  c._presetsDialog();
  const d = () => c.shadowRoot.querySelector(".dlg");
  assert.strictEqual(d().querySelectorAll(".ph").length, 3);
  d().querySelector(`.cell[data-e="${LIVING}"][data-p="warm"]`).click();
  d().querySelector(".cup").click();
  d().querySelector(".addp").click();
  const name = d().querySelector(".pname");
  name.value = "Comfort Plus";
  name.dispatchEvent(new w.Event("change"));
  const newCell = d().querySelector(`.cell[data-e="${OFFICE}"][data-p^="new"]`);
  newCell.click();
  d().querySelector(".cedit .nu").click();
  d().querySelector(".save").click();
  await new Promise((r) => setTimeout(r, 0));
  const [, svc, data] = JSON.parse(JSON.stringify(h.calls.pop()));
  assert.strictEqual(svc, "set_presets");
  same(data.presets.map((p) => p.id), ["eco", "warm", "sleep", "comfort_plus"]);
  assert.strictEqual(data.temperatures[LIVING].warm, 19.5);
  assert.strictEqual(data.temperatures[OFFICE].comfort_plus, 15);
  assert.strictEqual(data.temperatures[LIVING].comfort_plus, null);
  assert(!c.shadowRoot.querySelector(".dlg"));
});

test("presets dialog: Eco and Warm can't be removed, others can", () => {
  const c = render(intHass({ [LIVING]: room("Living Room", 20, 19, sched()) }));
  c._presetsDialog();
  c.shadowRoot.querySelector('.ph[data-h="0"]').click();
  assert(!c.shadowRoot.querySelector(".premove"));
  c.shadowRoot.querySelector('.ph[data-h="2"]').click();
  c.shadowRoot.querySelector(".premove").click();
  assert.strictEqual(c.shadowRoot.querySelectorAll(".ph").length, 2);
});

test("registers once, also when another copy of the card loaded first", () => {
  const before = w.customCards.length;
  w.eval(fs.readFileSync(CARD, "utf8").replace(/^const /gm, "var "));
  assert.strictEqual(w.customCards.filter((c) => c.type === "heating-control-card").length, 1);
  assert.strictEqual(w.customCards.length, before);
});

setTimeout(() => {
  console.log(`\n${n} tests passed`);
  process.exit(0);
}, 1500);
