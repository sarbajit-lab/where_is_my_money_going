// Auto-suggest for the sheet's text cells. Cells opt in with data-ac="<kind>"; the sheet supplies the suggestions.
//   Type to filter · ↑ ↓ choose · Enter / Tab accept the highlighted suggestion · Esc closes without accepting
import { esc } from "./util.js";

let pop = null;
let current = null;                 // { input, items, index, getOptions }
let quiet = false;                  // true while a picked value is being written (no new popup)
let windowBound = false;

function close() {
  if (pop) pop.remove();
  pop = current = null;
}

function mark(label, q) {
  if (!q) return esc(label);
  const i = label.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return esc(label);
  return `${esc(label.slice(0, i))}<b>${esc(label.slice(i, i + q.length))}</b>${esc(label.slice(i + q.length))}`;
}

function draw() {
  if (!current) return;
  const { input, items, index } = current;
  if (!items.length) { close(); return; }
  if (!pop) {
    pop = document.createElement("div");
    pop.className = "ac-pop";
    pop.setAttribute("role", "listbox");
    document.body.appendChild(pop);
    pop.addEventListener("mousedown", (e) => {
      e.preventDefault();                                   // keep the focus in the cell
      const el = e.target.closest("[data-i]");
      if (el && current) accept(+el.dataset.i, "mouse");
    });
  }
  const q = input.value.trim();
  pop.innerHTML = items.map((o, i) => `<div class="ac-item${i === index ? " on" : ""}${o.create ? " create" : ""}" data-i="${i}" role="option">
      <span class="ac-main">${o.create ? "＋ " : ""}${mark(o.label, o.create ? "" : q)}</span>
      ${o.sub ? `<span class="ac-sub">${esc(o.sub)}</span>` : ""}
      ${o.right ? `<span class="ac-right ${o.rightClass || ""}">${esc(o.right)}</span>` : ""}</div>`).join("");
  const r = input.getBoundingClientRect();
  const width = Math.max(r.width, 260);
  pop.style.minWidth = width + "px";
  const below = window.innerHeight - r.bottom;
  pop.style.left = Math.min(r.left, window.innerWidth - width - 8) + "px";
  if (below < 240 && r.top > below) { pop.style.top = ""; pop.style.bottom = window.innerHeight - r.top + 2 + "px"; }
  else { pop.style.bottom = ""; pop.style.top = r.bottom + 2 + "px"; }
  pop.querySelector(".on")?.scrollIntoView({ block: "nearest" });
}

function accept(i, key = "mouse") {
  if (!current) return;
  const { input, items } = current;
  const o = items[i];
  close();
  if (!o) return;
  quiet = true;
  input.value = o.value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new CustomEvent("ac:pick", { bubbles: true, detail: { ...o, key } }));
  quiet = false;
}

function open(input, getOptions, { explicit = false } = {}) {
  const q = input.value.trim();
  const items = getOptions(input, q);
  // highlight the top suggestion only when it begins with what was typed (so a new name is never replaced by accident)
  const first = items[0];
  const auto = first && !first.create && q && first.label.toLowerCase().startsWith(q.toLowerCase());
  current = { input, items, index: auto || explicit ? 0 : -1, getOptions };
  draw();
}

/** Attach to a container; getOptions(input, query) -> [{ value, label, sub?, right?, rightClass?, create? }] */
export function attachAutosuggest(root, getOptions) {
  const isAc = (el) => el && el.dataset && el.dataset.ac;
  root.addEventListener("focusin", (e) => { if (isAc(e.target)) open(e.target, getOptions); });
  root.addEventListener("input", (e) => { if (isAc(e.target) && !quiet) open(e.target, getOptions); });
  root.addEventListener("focusout", (e) => { if (isAc(e.target)) setTimeout(() => { if (current && current.input === e.target) close(); }, 0); });
  root.addEventListener("keydown", (e) => {
    if (!isAc(e.target)) return;
    if (!current || current.input !== e.target) {
      if (e.key === "ArrowDown") { open(e.target, getOptions, { explicit: true }); e.preventDefault(); }
      return;
    }
    const n = current.items.length;
    if (e.key === "ArrowDown") { current.index = (current.index + 1) % n; draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { current.index = (current.index - 1 + n) % n; draw(); e.preventDefault(); }
    else if (e.key === "Escape") { close(); e.stopPropagation(); }
    else if ((e.key === "Enter" || e.key === "Tab") && current.index >= 0) {
      const i = current.index;
      accept(i, e.key);
      if (e.key === "Enter") e.preventDefault();             // Tab continues to the next cell as usual
    }
  });
  if (!windowBound) {
    windowBound = true;
    window.addEventListener("scroll", (e) => { if (!(pop && pop.contains(e.target))) close(); }, true);
    window.addEventListener("resize", close);
  }
}

export const closeSuggestions = close;
