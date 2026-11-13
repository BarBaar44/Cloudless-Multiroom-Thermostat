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

test("waiting with central heating off by schedule: Heating off, no waiting note", () => {
  const v = read(render(intHass({ [HALL]: room("Hallway", 17.5, 19, { role: "waiting" }) }, "idle", { ch: false })));
  assert.strictEqual(v.winner, "Heating off");
  assert.strictEqual(v.sub, "Boiler idle");
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
