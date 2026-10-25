// Plain-node checks of the text widgets actually render, using shipped strings.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { withPluralForms } from "../static/widget-i18n.js";
import { spelledTime } from "../plugins/clock_word/client.js";
import { suffixFor } from "../plugins/countdown_date/client.js";

function translator(widget, locale = "pl") {
  const strings = JSON.parse(readFileSync(new URL(`../plugins/${widget}/strings/${locale.split("-")[0]}.json`, import.meta.url)));
  return (key, fallback) => strings[key] ?? fallback ?? key;
}

async function html(widget, data = {}, options = {}, locale = "pl", fragment = "full") {
  const { default: render } = await import(`../plugins/${widget}/client.js`);
  const shadow = {
    innerHTML: "",
    querySelector: () => null,
    querySelectorAll: () => [],
    host: { getBoundingClientRect: () => ({ width: 400, height: 800 }) },
  };
  render(shadow, {
    data, locale, t: translator(widget, locale), fragment,
    cell: { options, fragment, size: "lg", w: 400, h: 800 },
  });
  return shadow.innerHTML;
}

const forms = [
  [0, "many"], [1, "one"], [2, "few"], [3, "few"], [4, "few"],
  [5, "many"], [12, "many"], [13, "many"], [14, "many"], [21, "many"],
  [22, "few"], [23, "few"], [24, "few"], [25, "many"], [101, "many"],
  [112, "many"], [122, "few"],
];
for (const locale of ["pl", "pl-PL"]) {
  for (const [n, form] of forms) {
    const t = withPluralForms(translator("calendar_week"), locale);
    assert.equal(t("events", "events", n), form === "few" ? "wydarzenia" : "wydarzeń");
    if (n > 0) {
      const noun = n === 1 ? "wydarzenie" : form === "few" ? "wydarzenia" : "wydarzeń";
      const weekly = await html("calendar_week", { days: [{ date: "2026-01-05", events: Array.from({ length: n }, () => ({ all_day: true, summary: "Meeting" })) }] }, {}, locale);
      assert.ok(weekly.includes(`title="${n} ${noun}"`), `week count ${n}`);
      const stop = n === 1 ? "przystanek" : form === "few" ? "przystanki" : "przystanków";
      for (const fragment of ["full", "next", "list"]) {
        const board = await html("gtfs", { arrivals: [{ stops_away: n, minutes: 10 }] }, { show_stops_away: true }, locale, fragment);
        assert.ok(board.includes(`${n} ${stop}`), `${fragment}: stop count ${n}`);
      }
    }
    const hours = n === 1 ? "godzina" : form === "few" ? "godziny" : "godzin";
    const countdownT = withPluralForms(translator("countdown_date"), locale);
    assert.equal(suffixFor("hour", n, false, countdownT), `${hours} do końca`);
    assert.equal(suffixFor("hour", -n, true, countdownT), `${n === 1 ? "godzinę" : hours} temu`);
    const trigger = n === 1 ? "uruchomienie" : form === "few" ? "uruchomienia" : "uruchomień";
    const automation = { automations: [{ eid: "test" }], total_24h: n, most_fired: { name: "Test", c7: n }, least_fired: { name: "Test", c7: n } };
    const bar = await html("ha_automation_history", automation, {}, locale, "bar");
    assert.ok(bar.includes(`<small>${trigger} · 24 h</small>`), `bar count ${n}`);
    const ranking = await html("ha_automation_history", automation, {}, locale);
    assert.equal(ranking.split(`${n} ${trigger}</div>`).length - 1, 2, `both rankings: ${n}`);
    for (const kind of ["critical", "low"]) {
      const adjective = kind === "critical"
        ? n === 1 ? "KRYTYCZNA" : form === "few" ? "KRYTYCZNE" : "KRYTYCZNYCH"
        : n === 1 ? "NISKA" : form === "few" ? "NISKIE" : "NISKICH";
      if (n === 0) continue;
      const batteries = await html("ha_battery", { items: [{ name: "Battery", [kind]: true }], summary: { [kind]: n } }, {}, locale);
      assert.ok(batteries.includes(`${n} ${adjective}</span>`), `${kind} summary ${n}`);
      assert.ok(batteries.includes(kind === "critical" ? "KRYTYCZNA" : "NISKA"), `${kind} pill remains singular`);
    }
    const degree = n === 1 ? "stopień" : form === "few" ? "stopnie" : "stopni";
    for (const temperature of [n, -n]) {
      const status = await html("tesserae_status", { show_temperature: true, temperature_c: temperature }, {}, locale);
      assert.ok(status.includes(`Temperatura ${temperature} ${degree} C`), `temperature ${temperature}`);
    }
  }
}

// Missing variants retain the base translation, English fallback, or bare key.
const french = withPluralForms(translator("calendar_week", "fr"), "fr");
assert.equal(french("events", "events", 2), "événements");
const untranslated = withPluralForms(undefined);
assert.equal(untranslated("events", "events", 2), "events");
assert.equal(untranslated("unknown"), "unknown");
assert.equal(untranslated("events", "events"), "events");

const RealDate = Date;
let now = new RealDate(2026, 0, 15, 12);
globalThis.Date = class extends RealDate {
  constructor(...args) { super(...(args.length ? args : [now.getTime()])); }
  static now() { return now.getTime(); }
};
try {
  for (const n of [1, 2, 3, 4, 5, 12, 14, 21, 22, 24, 25, 50, 51]) {
    now = new RealDate(2026, 0, 1 + n * 7, 12);
    const year = await html("year_progress", {}, { mode: "life-weeks", birth_year: 2026, life_expectancy_years: 1 });
    const weeks = (n) => n === 1 ? "tydzień" : [2, 3, 4, 22, 23, 24].includes(n) ? "tygodnie" : "tygodni";
    assert.ok(year.includes(`${n} ${weeks(n)} ${n === 1 ? "przeżyty" : weeks(n) === "tygodnie" ? "przeżyte" : "przeżytych"}`), `weeks lived ${n}`);
    assert.ok(year.includes(`${52 - n} ${weeks(52 - n)} do końca`), `weeks remaining ${52 - n}`);
  }
  now = new RealDate(2026, 0, 15, 12);
  assert.ok((await html("ha_todo", { items: [{ summary: "Task", due: "2026-01-12" }] })).includes("3 dni po terminie"));
  assert.ok((await html("ha_locks", { entries: [{ name: "Door", secured: false, last_changed: "2026-01-12T12:00:00" }] })).includes("3 dn."));
  for (const n of [1, 2, 5]) {
    const since = new RealDate(now.getTime() - n * 86400000).toISOString();
    const expected = `${n} ${n === 1 ? "dzień" : "dni"} temu`;
    assert.ok((await html("ha_camera", { items: [{ name: "Camera", last_updated: since, image_url: "/test.jpg" }] })).includes(expected));
    assert.ok((await html("device_battery", { devices: [{ name: "Panel", pct: 50, seconds_ago: n * 86400 }] })).includes(expected));
  }
} finally {
  globalThis.Date = RealDate;
}

// Every hour, including midnight/noon rollover, needs the correct genitive.
const genitives = ["dwunastej", "pierwszej", "drugiej", "trzeciej", "czwartej", "piątej", "szóstej", "siódmej", "ósmej", "dziewiątej", "dziesiątej", "jedenastej"];
const clockT = translator("clock_word");
for (let hour = 0; hour < 24; hour++) {
  assert.equal(spelledTime(new Date(2026, 0, 1, hour, 5), clockT), `Pięć po ${genitives[hour % 12]}`);
  assert.equal(spelledTime(new Date(2026, 0, 1, hour, 30), clockT), `Wpół do ${genitives[(hour + 1) % 12]}`);
}
for (const [minute, text] of [[0, "Trzecia"], [10, "Dziesięć po trzeciej"], [15, "Kwadrans po trzeciej"], [20, "Dwadzieścia po trzeciej"], [25, "Dwadzieścia pięć po trzeciej"], [35, "Za dwadzieścia pięć czwarta"], [40, "Za dwadzieścia czwarta"], [45, "Za kwadrans czwarta"], [50, "Za dziesięć czwarta"], [55, "Za pięć czwarta"], [59, "Za pięć czwarta"]]) {
  assert.equal(spelledTime(new Date(2026, 0, 1, 15, minute), clockT), text);
}
assert.equal(spelledTime(new Date(2026, 0, 1, 15, 30), translator("clock_word", "en")), "Half past three");
assert.equal(spelledTime(new Date(2026, 0, 1, 15, 30), translator("clock_word", "de")), "Halb vier");
const polishDate = await html("news_wikipedia_otd", { date: "25 October", items: [] });
assert.ok(polishDate.includes("<h3>25 października</h3>"));
assert.ok((await html("news_wikipedia_otd", { date: "25 October", items: [] }, {}, "en")).includes("<h3>On 25 October</h3>"));

console.log("widget_i18n_check.mjs: all assertions passed");
