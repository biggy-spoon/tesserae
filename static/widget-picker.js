// Cell widget picker: a search box over every installed widget, grouped by
// category, that swaps a hidden form input.
//
// Markup (see templates/page_editor.html, cell_form):
//
//   <div data-widget-picker>
//     <input type="hidden" name="plugin" data-reload-on-change="1" data-wp-value>
//     <div data-wp-box><i data-wp-icon></i><input data-wp-input role="combobox"></div>
//     <div data-wp-list role="listbox" hidden></div>
//   </div>
//
// Entries come from one page-wide <script type="application/json"
// id="widget-picker-data"> ({categories, widgets}), built by
// app/widget_picker.py. Picking a widget sets the hidden input and fires a
// bubbling ``change`` on it, so editor.js saves every form and reloads the
// page exactly as it did for the old <select>. The search box has no name and
// keeps its own input/change events to itself, so typing a query never marks
// the dashboard dirty or re-renders the preview.

(function () {
  const RECENT_KEY = "tesserae-recent-widgets";
  const RECENT_MAX = 5;

  let data = null;
  function load() {
    if (data) return data;
    const el = document.getElementById("widget-picker-data");
    try {
      data = el ? JSON.parse(el.textContent) : null;
    } catch (err) {
      console.error("[widget-picker] bad picker data:", err);
    }
    data = data || { categories: [], widgets: [] };
    data.byId = new Map(data.widgets.map((w) => [w.id, w]));
    data.catLabel = new Map(data.categories.map((c) => [c.id, c.label]));
    return data;
  }

  function readRecent() {
    try {
      const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(raw) ? raw.filter((id) => typeof id === "string") : [];
    } catch {
      return [];
    }
  }
  function pushRecent(id) {
    try {
      const next = [id, ...readRecent().filter((x) => x !== id)].slice(0, RECENT_MAX);
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
    } catch {
      /* private mode / storage disabled: recents are a convenience */
    }
  }

  const fullName = (w) => (w.family ? `${w.family}, ${w.item}` : w.item);
  const fold = (s) =>
    String(s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, " ");

  // Every query word has to hit somewhere. Lower scores rank first: the
  // item name, then the whole name, then a word inside it, then the id,
  // the category label and finally the description.
  function search(q) {
    const d = load();
    const terms = fold(q).split(" ").filter(Boolean);
    const hits = [];
    for (const w of d.widgets) {
      const item = fold(w.item);
      const name = fold(fullName(w));
      const id = fold(w.id);
      const cat = fold(d.catLabel.get(w.category));
      const desc = fold(w.desc);
      let score = 0;
      let ok = true;
      for (const t of terms) {
        if (item.startsWith(t)) score += 0;
        else if (name.startsWith(t)) score += 1;
        else if ((" " + name).includes(" " + t)) score += 2;
        else if (name.includes(t)) score += 3;
        else if (id.includes(t)) score += 4;
        else if (cat.includes(t)) score += 5;
        else if (desc.includes(t)) score += 7;
        else {
          ok = false;
          break;
        }
      }
      if (ok) hits.push([score, w]);
    }
    hits.sort((a, b) => a[0] - b[0] || fullName(a[1]).localeCompare(fullName(b[1])));
    return hits.map((h) => h[1]);
  }

  // Text with every query word wrapped in <mark>, built as DOM nodes so a
  // widget name never reaches innerHTML.
  function highlight(text, q) {
    const frag = document.createDocumentFragment();
    const terms = fold(q).split(" ").filter(Boolean);
    const folded = fold(text);
    // fold() keeps one character per input character for everything but
    // decomposed accents, so only highlight when the lengths agree.
    if (!terms.length || folded.length !== text.length) {
      frag.append(text);
      return frag;
    }
    const marks = new Array(text.length).fill(false);
    for (const t of terms) {
      let i = folded.indexOf(t);
      while (i !== -1) {
        for (let j = i; j < i + t.length; j++) marks[j] = true;
        i = folded.indexOf(t, i + t.length);
      }
    }
    let i = 0;
    while (i < text.length) {
      let j = i;
      while (j < text.length && marks[j] === marks[i]) j++;
      const chunk = text.slice(i, j);
      if (marks[i]) {
        const m = document.createElement("mark");
        m.textContent = chunk;
        frag.append(m);
      } else {
        frag.append(chunk);
      }
      i = j;
    }
    return frag;
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function bind(root) {
    if (root.dataset.wpBound) return;
    root.dataset.wpBound = "1";
    const d = load();
    const value = root.querySelector("[data-wp-value]");
    const box = root.querySelector("[data-wp-box]");
    const input = root.querySelector("[data-wp-input]");
    const icon = root.querySelector("[data-wp-icon]");
    const list = root.querySelector("[data-wp-list]");
    if (!value || !input || !list) return;

    const listId = list.id;
    let open = false;
    let active = 0;
    let rows = []; // [{w, node}] in display order; w null = "No widget"

    function current() {
      return d.byId.get(value.value) || null;
    }
    function showCurrent() {
      const w = current();
      input.value = w ? fullName(w) : value.value;
      if (icon) icon.className = `ph ${w ? w.icon : "ph-squares-four"} wp-icon`;
    }

    function optionNode(w, q, idx) {
      const node = el("div", "wp-opt");
      node.id = `${listId}-o${idx}`;
      node.setAttribute("role", "option");
      node.dataset.idx = String(idx);
      if (!w) {
        node.classList.add("wp-opt-clear");
        node.append(el("i", "ph ph-prohibit wp-opt-icon"), el("span", "wp-opt-name", "No widget"));
        return node;
      }
      const ic = el("i", `ph ${w.icon} wp-opt-icon`);
      ic.setAttribute("aria-hidden", "true");
      const name = el("span", "wp-opt-name");
      if (w.family) {
        const fam = el("span", "wp-fam");
        fam.append(highlight(w.family, q), ",");
        name.append(fam, " ");
      }
      const item = el("span", "wp-item");
      item.append(highlight(w.item, q));
      name.append(item);
      node.append(ic, name);
      if (q && w.desc) {
        const desc = el("span", "wp-opt-desc");
        desc.append(highlight(w.desc, q));
        name.append(desc);
      }
      if (w.id === value.value) {
        node.classList.add("is-current");
        const tick = el("i", "ph-bold ph-check wp-opt-tick");
        tick.setAttribute("aria-hidden", "true");
        node.append(tick);
      }
      node.title = w.desc || "";
      return node;
    }

    function group(label, count) {
      const g = el("div", "wp-group");
      g.setAttribute("role", "presentation");
      g.append(el("span", null, label));
      if (count != null) g.append(el("span", "wp-count", String(count)));
      return g;
    }

    function render() {
      const q = open ? input.value.trim() : "";
      list.replaceChildren();
      rows = [];
      const add = (w) => {
        const node = optionNode(w, q, rows.length);
        rows.push({ w, node });
        list.append(node);
      };
      if (!q) {
        if (value.value) add(null);
        const recent = readRecent()
          .map((id) => d.byId.get(id))
          .filter(Boolean);
        if (recent.length) {
          list.append(group("Recent"));
          recent.forEach(add);
        }
        for (const c of d.categories) {
          const ws = d.widgets.filter((w) => w.category === c.id);
          if (!ws.length) continue;
          list.append(group(c.label, ws.length));
          ws.forEach(add);
        }
      } else {
        const hits = search(q);
        if (hits.length) {
          list.append(group(`${hits.length} ${hits.length === 1 ? "match" : "matches"}`));
          hits.forEach(add);
        } else {
          list.append(el("div", "wp-empty", `No widget matches “${q}”.`));
        }
      }
      const hint = el("div", "wp-hint");
      hint.setAttribute("aria-hidden", "true");
      hint.textContent = "↑↓ move · Enter picks · Esc closes";
      list.append(hint);
      if (!q && active === 0) {
        // Land on the current widget so Enter on an untouched list is a no-op.
        const at = rows.findIndex((r) => r.w && r.w.id === value.value);
        if (at >= 0) active = at;
      }
      setActive(Math.min(active, rows.length - 1), !q);
    }

    function setActive(i, center) {
      rows.forEach((r) => r.node.setAttribute("aria-selected", "false"));
      active = Math.max(0, i);
      const r = rows[active];
      if (!r) {
        input.removeAttribute("aria-activedescendant");
        return;
      }
      r.node.setAttribute("aria-selected", "true");
      input.setAttribute("aria-activedescendant", r.node.id);
      r.node.scrollIntoView({ block: center ? "center" : "nearest" });
    }

    function openList() {
      if (open) return;
      open = true;
      active = 0;
      input.value = "";
      input.placeholder = `Search ${d.widgets.length} widgets`;
      list.hidden = false;
      box.classList.add("is-open");
      input.setAttribute("aria-expanded", "true");
      render();
    }
    function closeList() {
      if (!open) return;
      open = false;
      list.hidden = true;
      box.classList.remove("is-open");
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      input.placeholder = "Pick a widget";
      showCurrent();
    }

    function pick(w) {
      const id = w ? w.id : "";
      closeList();
      if (id === value.value) return;
      if (w) pushRecent(id);
      value.value = id;
      showCurrent();
      value.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // Keep the query's own events away from editor.js's dirty/preview
    // listeners on the form.
    input.addEventListener("input", (ev) => {
      ev.stopPropagation();
      if (!open) openList();
      active = 0;
      render();
      list.scrollTop = 0;
    });
    input.addEventListener("change", (ev) => ev.stopPropagation());
    input.addEventListener("focus", openList);
    input.addEventListener("click", openList);
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") ev.preventDefault(); // never submit the cell form
      if (!open) {
        if (ev.key === "ArrowDown" || ev.key === "Enter") openList();
        return;
      }
      if (ev.key === "ArrowDown") {
        setActive(Math.min(rows.length - 1, active + 1));
        ev.preventDefault();
      } else if (ev.key === "ArrowUp") {
        setActive(active - 1);
        ev.preventDefault();
      } else if (ev.key === "PageDown" || ev.key === "PageUp") {
        setActive(Math.min(rows.length - 1, active + (ev.key === "PageDown" ? 8 : -8)));
        ev.preventDefault();
      } else if (ev.key === "Enter") {
        if (rows[active]) pick(rows[active].w);
      } else if (ev.key === "Escape") {
        closeList();
        ev.preventDefault();
      } else if (ev.key === "Tab") {
        closeList();
      }
    });
    box.addEventListener("mousedown", (ev) => {
      if (ev.target === input) return;
      ev.preventDefault();
      if (open) closeList();
      else input.focus();
    });
    // mousedown, not click, so the input keeps focus and blur doesn't
    // close the list before the pick lands.
    list.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      const opt = ev.target.closest(".wp-opt");
      if (opt) pick(rows[Number(opt.dataset.idx)].w);
    });
    input.addEventListener("blur", closeList);
    showCurrent();
  }

  function bindAll(scope) {
    (scope || document).querySelectorAll("[data-widget-picker]").forEach(bind);
  }
  window.tesseraeWidgetPickerBindAll = bindAll;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => bindAll());
  } else {
    bindAll();
  }
})();
