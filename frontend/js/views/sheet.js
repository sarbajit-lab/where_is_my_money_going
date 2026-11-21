// The weekly sheet: type many entries like in a spreadsheet, with suggestions from your history and live limits.
//   Tab / Enter  next cell      Ctrl+Enter or Ctrl+S  save all      ↑ ↓ in a date cell  change the day
//   Paste rows copied from Excel into any cell of the new-entries block.
import { api } from "../api.js";
import { attachAutosuggest, closeSuggestions } from "../ac.js";
import { session, can } from "../state.js";
import { $, $$, bindMonthPicker, confirmDialog, esc, monthLabel, monthPicker, money, pad, shiftMonth, thisMonth, todayISO, toast } from "../util.js";

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DRAFT_KEY = "wimmg:sheet-drafts";

const S = {
  month: thisMonth(), boot: null, itemMap: new Map(), accMap: new Map(), spent: {}, saved: [],
  drafts: [], seq: 0, search: "", autosave: true, editable: true, busy: false,
};

// ---------------------------------------------------------------- small helpers

const fmtDate = (iso) => { if (!iso) return ""; const [y, m, d] = iso.split("-"); return `${MON[+m - 1]} ${+d}, ${y}`; };
const lower = (s) => String(s || "").trim().toLowerCase();
const num = (v) => { const n = parseFloat(String(v ?? "").replace(/[,₹\s]/g, "")); return isNaN(n) ? 0 : n; };
const monthOf = (iso) => (iso ? iso.slice(0, 7) : S.month);
const cid = () => `n${++S.seq}`;

function isoOk(y, m, d) {
  const dt = new Date(y, m - 1, d);
  return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d ? `${y}-${pad(m)}-${pad(d)}` : null;
}

/** Understands: 5 · 5/11 · 5-11-26 · 5 nov · nov 5 · nov 5, 2026 · 2026-11-05 · t (today) · y (yesterday) */
export function parseDate(text) {
  const t = String(text || "").trim().toLowerCase().replace(/,/g, " ").replace(/\s+/g, " ");
  if (!t) return "";
  const [cy, cm] = S.month.split("-").map(Number);
  if (t === "t" || t === "today") return todayISO();
  if (t === "y" || t === "yesterday") { const d = new Date(); d.setDate(d.getDate() - 1); return isoOk(d.getFullYear(), d.getMonth() + 1, d.getDate()); }
  let m;
  if ((m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) return isoOk(+m[1], +m[2], +m[3]);
  if ((m = t.match(/^(\d{1,2})$/))) return isoOk(cy, cm, +m[1]);
  if ((m = t.match(/^(\d{1,2})[\/.\-](\d{1,2})(?:[\/.\-](\d{2}|\d{4}))?$/))) {
    const y = m[3] ? (m[3].length === 2 ? 2000 + +m[3] : +m[3]) : cy;
    return isoOk(y, +m[2], +m[1]);
  }
  const mi = (w) => MON.findIndex((x) => w.startsWith(x.toLowerCase())) + 1;
  if ((m = t.match(/^(\d{1,2}) ([a-z]{3,9})(?: (\d{2}|\d{4}))?$/)) && mi(m[2])) {
    return isoOk(m[3] ? (m[3].length === 2 ? 2000 + +m[3] : +m[3]) : cy, mi(m[2]), +m[1]);
  }
  if ((m = t.match(/^([a-z]{3,9}) (\d{1,2})(?: (\d{2}|\d{4}))?$/)) && mi(m[1])) {
    return isoOk(m[3] ? (m[3].length === 2 ? 2000 + +m[3] : +m[3]) : cy, mi(m[1]), +m[2]);
  }
  return null;
}

function shiftISO(iso, n) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// ---------------------------------------------------------------- data model

function defaultDate() {
  const last = [...S.drafts].reverse().find((d) => d.date);
  if (last && monthOf(last.date) === S.month) return last.date;
  return S.month === thisMonth() ? todayISO() : `${S.month}-01`;
}

function blank() {
  return { cid: cid(), id: null, date: defaultDate(), kind: "expense", item: "", category: "", amount: "", paid_from: "", should_pay: "",
    note: "", auto: { paid_from: false, should_pay: false }, status: "", error: "", dirty: false };
}

const itemInfo = (name) => S.itemMap.get(lower(name));
const hasAccount = (name) => !name || S.accMap.has(lower(name));
const isNewItem = (r) => !!lower(r.item) && !itemInfo(r.item);
const newAccounts = (r) => [r.paid_from, r.should_pay].filter((n) => lower(n) && !S.accMap.has(lower(n)));
const needsConfirm = (r) => isNewItem(r) || newAccounts(r).length > 0;
const complete = (r) => !!r.date && !!lower(r.item) && num(r.amount) > 0;
const blankRow = (r) => !lower(r.item) && !r.amount && !r.paid_from && !r.should_pay && !r.note;
const payload = (r) => ({ date: r.date, kind: r.kind, item: r.item.trim(), category: r.category, amount: num(r.amount),
  paid_from: r.paid_from.trim(), should_pay: r.should_pay.trim(), note: r.note.trim() });

function rebuildMaps() {
  S.itemMap = new Map(S.boot.items.map((i) => [lower(i.name), i]));
  S.accMap = new Map(S.boot.accounts.map((a) => [lower(a.name), a]));
}

const spentOf = (month, itemId) => ((S.spent[month] || {})[itemId]) || 0;

/** Limit left after this row, in entry order: saved rows come first, then drafts from the top down. */
function draftLeft(r) {
  const it = itemInfo(r.item);
  if (!it || r.kind !== "expense" || it.limit === null || !r.date) return null;
  const mo = monthOf(r.date);
  let used = spentOf(mo, it.id);
  for (const d of S.drafts) {
    if (d.cid === r.cid) break;
    if (d.kind === "expense" && lower(d.item) === lower(r.item) && monthOf(d.date) === mo) used += num(d.amount);
  }
  return it.limit - used - num(r.amount);
}

function saveDrafts() {
  try {
    const keep = S.drafts.filter((d) => !blankRow(d)).map(({ status, error, ...rest }) => rest);
    if (keep.length) sessionStorage.setItem(DRAFT_KEY, JSON.stringify(keep)); else sessionStorage.removeItem(DRAFT_KEY);
  } catch { /* storage blocked: drafts just aren't remembered */ }
}

function loadDrafts() {
  try {
    const raw = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "[]");
    return raw.map((d) => ({ ...blank(), ...d, cid: cid(), id: null, status: "", error: "" }));
  } catch { return []; }
}

// ---------------------------------------------------------------- rendering

function leftHtml(left) {
  if (left === null || left === undefined) return `<span class="faint">—</span>`;
  const cls = left < 0 ? "over" : left === 0 ? "zero" : "ok";
  return `<span class="left ${cls}" title="${left < 0 ? "Over the monthly limit" : "Left of the monthly limit after this row"}">${left < 0 ? "−" : ""}${money(Math.abs(left)).replace(/^−/, "")}</span>`;
}

function rowHtml(r) {
  const saved = r.id !== null;
  const it = itemInfo(r.item);
  const newItem = isNewItem(r);
  const ro = S.editable ? "" : "readonly";
  const left = saved ? r.limit_left : draftLeft(r);
  const bad = (name) => (lower(name) && !S.accMap.has(lower(name)) ? " new" : "");
  return `<tr class="sr ${saved ? "saved" : "draft"} ${r.status}" data-cid="${r.cid}" ${saved ? `data-id="${r.id}"` : ""}>
    <td class="c-date"><input data-f="date" value="${esc(fmtDate(r.date))}" placeholder="Date" autocomplete="off" ${ro}></td>
    <td class="c-kind"><button type="button" tabindex="-1" class="kind ${r.kind}" data-act="kind" title="Expense or income (click to switch)" ${S.editable ? "" : "disabled"}>${r.kind === "income" ? "In" : "Out"}</button></td>
    <td class="c-item"><input data-f="item" data-ac="item" value="${esc(r.item)}" placeholder="Item" autocomplete="off" ${ro}></td>
    <td class="c-cat">${newItem
      ? `<input data-f="category" data-ac="category" class="newcat" value="${esc(r.category)}" placeholder="New item: category" autocomplete="off" ${ro}>`
      : `<span class="cat-chip">${esc(it ? it.category : "")}</span>`}</td>
    <td class="c-amt"><input data-f="amount" class="num" inputmode="decimal" value="${esc(r.amount)}" placeholder="${esc(lastAmountHint(r))}" autocomplete="off" ${ro}></td>
    <td class="c-pf"><input data-f="paid_from" data-ac="account" class="${bad(r.paid_from)}" value="${esc(r.paid_from)}" placeholder="${r.kind === "income" ? "Received in" : "Paid from"}" autocomplete="off" ${ro}></td>
    <td class="c-sp"><input data-f="should_pay" data-ac="account" class="${bad(r.should_pay)}" value="${esc(r.should_pay)}" placeholder="${r.kind === "income" ? "Belongs to" : "Should pay"}" autocomplete="off" ${ro}></td>
    <td class="c-left num" data-left>${leftHtml(left)}</td>
    <td class="c-note"><input data-f="note" value="${esc(r.note)}" placeholder="Note" autocomplete="off" ${ro}></td>
    <td class="c-act">${S.editable ? `<button type="button" tabindex="-1" class="x" data-act="del" title="${saved ? "Delete this entry" : "Remove this row"}">✕</button>` : ""}</td>
    <td class="c-state" data-state>${stateHtml(r)}</td>
  </tr>`;
}

function stateHtml(r) {
  if (r.status === "saving") return `<span class="st saving" title="Saving">…</span>`;
  if (r.status === "error") return `<span class="st err" title="${esc(r.error)}">⚠ ${esc(r.error)}</span>`;
  if (r.id === null && needsConfirm(r) && !blankRow(r)) {
    const bits = [];
    if (isNewItem(r)) bits.push(`item “${r.item.trim()}”`);
    newAccounts(r).forEach((a) => bits.push(`account “${a.trim()}”`));
    return `<span class="st warn" title="Saved with Save all, after you confirm">New ${esc(bits.join(", "))}</span>`;
  }
  return "";
}

function lastAmountHint(r) {
  const it = itemInfo(r.item);
  const h = it && S.boot.hints[it.id];
  return h ? `last ${money(h.last_amount)}` : "Amount";
}

const COLS = `<colgroup><col class="w-date"><col class="w-kind"><col class="w-item"><col class="w-cat"><col class="w-amt"><col class="w-pf"><col class="w-sp"><col class="w-left"><col class="w-note"><col class="w-act"><col class="w-state"></colgroup>`;
const HEAD = `<thead><tr><th>Date</th><th></th><th>Item</th><th>Category</th><th class="num">Amount</th><th>Paid from</th><th>Should pay</th><th class="num">Limit left</th><th>Note</th><th></th><th></th></tr></thead>`;

export async function render(params = {}) {
  S.editable = can("data.write");
  S.autosave = session.autosave && S.editable;
  if (params.month) S.month = params.month;
  $("#view").innerHTML = `<div id="sheet-root">
    <div class="page-head sheet-head">
      <div><h1>Sheet</h1><div class="sub small muted">Type a week of entries, then move on. Suggestions come from your history.</div></div>
      <div class="toolbar">
        <div class="month-nav">
          <button class="btn btn-icon" id="m-prev" aria-label="Previous month">‹</button>
          <div id="m-pick"></div>
          <button class="btn btn-icon" id="m-next" aria-label="Next month">›</button>
        </div>
        ${S.editable ? `<label class="small muted autosave" title="Save a row as soon as you leave it"><input type="checkbox" id="autosave" ${S.autosave ? "checked" : ""}> Auto-save rows</label>
        <button class="btn btn-primary" id="save-all" disabled>Save all</button>` : `<span class="status-pill off">Read-only</span>`}
      </div>
    </div>
    <div class="sheet-layout">
      <div class="sheet-main">
        ${S.editable ? `<section class="panel sheet-block" id="new-block">
          <div class="panel-head"><h2>New entries</h2><span class="small faint" id="new-count"></span></div>
          <div class="grid-wrap"><table class="sheet-grid" id="new-grid">${COLS}${HEAD}<tbody></tbody></table></div>
          <div class="grid-help small faint">Tab / Enter: next cell · Tab on the last cell adds a row · Ctrl+Enter: save all · ↑ ↓ in a date: change day · type <b>t</b> for today ·
            you can paste rows copied from Excel</div>
        </section>` : ""}
        <section class="panel sheet-block">
          <div class="panel-head"><h2 id="saved-title">Entries</h2>
            <input type="search" id="search" placeholder="Search all months…" value="${esc(S.search)}" style="max-width:220px"></div>
          <div class="totals-strip" id="totals"></div>
          <div class="grid-wrap"><table class="sheet-grid" id="saved-grid">${COLS}${HEAD}<tbody></tbody></table></div>
          <div class="empty small hidden" id="saved-empty">No entries for this month yet.</div>
        </section>
      </div>
      <aside class="sheet-side"><section class="panel" id="side"></section></aside>
    </div></div>`;
  $("#m-pick").innerHTML = monthPicker("m-input", S.month);
  bindMonthPicker($("#m-input"));
  S.drafts = S.editable ? loadDrafts() : [];
  if (S.editable && !S.drafts.some(blankRow)) S.drafts.push(blank());
  await loadMonth();
  bind();
  if (S.editable) focusCell(S.drafts[S.drafts.length - 1].cid, "item");
}

async function loadMonth(keepFocus = false) {
  const [boot, list] = await Promise.all([
    api.sheetBoot(S.month),
    api.sheetEntries(S.search ? { q: S.search, order: "desc", limit: 300 } : { month: S.month, order: "desc", limit: 3000 }),
  ]);
  S.boot = boot;
  S.spent = { ...S.spent, [S.month]: boot.spent };
  rebuildMaps();
  S.saved = list.rows.map((e) => ({ ...e, cid: `s${e.id}`, amount: String(e.amount), paid_from: e.paid_from || "", should_pay: e.should_pay || "",
    auto: {}, status: "", error: "", dirty: false }));
  S.listTotals = list;
  if (!keepFocus) { renderDrafts(); renderSaved(); }
  renderTotals();
  renderSide();
}

function renderDrafts() {
  const tb = $("#new-grid tbody");
  if (!tb) return;
  tb.innerHTML = S.drafts.map(rowHtml).join("");
  updateCounts();
}

function renderSaved() {
  $("#saved-grid tbody").innerHTML = S.saved.map(rowHtml).join("");
  $("#saved-empty").classList.toggle("hidden", S.saved.length > 0);
  $("#saved-title").textContent = S.search ? `Search results for “${S.search}”` : `Entries · ${monthLabel(S.month)}`;
}

function renderTotals() {
  const t = S.listTotals;
  const pending = S.drafts.filter((d) => complete(d) && d.kind === "expense" && monthOf(d.date) === S.month).reduce((a, d) => a + num(d.amount), 0);
  $("#totals").innerHTML = `
    <div class="ts-item"><span class="ts-k">Entries</span><span class="ts-v">${t.total.toLocaleString("en-IN")}</span></div>
    <div class="ts-item"><span class="ts-k">Spent</span><span class="ts-v c-expense">${money(t.expense)}</span></div>
    <div class="ts-item"><span class="ts-k">Received</span><span class="ts-v c-income">${money(t.income)}</span></div>
    ${pending ? `<div class="ts-item"><span class="ts-k">Not saved yet</span><span class="ts-v">+${money(pending)}</span></div>` : ""}`;
}

function updateCounts() {
  const ready = S.drafts.filter((d) => complete(d)).length;
  const partial = S.drafts.filter((d) => !blankRow(d) && !complete(d)).length;
  const c = $("#new-count");
  if (c) c.textContent = ready || partial ? `${ready} ready${partial ? ` · ${partial} incomplete` : ""}` : "";
  const b = $("#save-all");
  if (b) { b.disabled = !ready || S.busy; b.textContent = ready ? `Save all (${ready})` : "Save all"; }
}

// ---- the limits panel (right side): live, includes rows you haven't saved yet
function renderSide() {
  const el = $("#side");
  if (!el || !S.boot) return;
  const pend = {};
  S.drafts.forEach((d) => {
    const it = itemInfo(d.item);
    if (it && d.kind === "expense" && complete(d) && monthOf(d.date) === S.month) pend[it.id] = (pend[it.id] || 0) + num(d.amount);
  });
  const rows = S.boot.items.map((i) => ({ ...i, spent: spentOf(S.month, i.id), pend: pend[i.id] || 0 }))
    .filter((i) => i.limit !== null || i.spent || i.pend);
  const cats = {};
  rows.forEach((i) => {
    const c = (cats[i.category] ||= { name: i.category, spent: 0, limit: 0, items: [] });
    c.spent += i.spent + i.pend; c.limit += i.limit || 0; c.items.push(i);
  });
  const list = Object.values(cats).sort((a, b) => a.name.localeCompare(b.name));
  const total = rows.reduce((a, i) => a + i.spent + i.pend, 0);
  el.innerHTML = `<div class="panel-head"><h2>Limits · ${esc(monthLabel(S.month))}</h2><span class="small faint">${money(total)} spent</span></div>
    <div class="side-body">${list.map((c) => `
      <div class="lim-cat"><div class="lim-cat-h"><b>${esc(c.name)}</b>
        <span class="small muted">${money(c.spent)}${c.limit ? ` of ${money(c.limit)}` : ""}</span></div>
        ${c.items.sort((a, b) => (b.spent + b.pend) / (b.limit || 1) - (a.spent + a.pend) / (a.limit || 1)).map(limRow).join("")}
      </div>`).join("") || `<div class="empty small">Set monthly limits under <a href="#/limits">Limits</a> and they show up here.</div>`}</div>`;
}

function limRow(i) {
  const used = i.spent + i.pend;
  const pct = i.limit ? Math.min(100, (used / i.limit) * 100) : 0;
  const left = i.limit === null ? null : i.limit - used;
  const cls = left === null ? "" : left < 0 ? "over" : used / i.limit >= 0.8 ? "warn" : "";
  return `<div class="lim-row ${i.pend ? "touched" : ""}" title="${esc(i.name)}">
    <div class="lim-top"><span class="lim-name">${esc(i.name)}</span>
      <span class="lim-left ${cls}">${left === null ? money(used) : left < 0 ? `over ${money(-left)}` : `${money(left)} left`}</span></div>
    ${i.limit ? `<div class="lim-bar"><i class="${cls}" style="width:${pct}%"></i>${i.pend ? `<i class="pend" style="width:${Math.min(100 - pct, (i.pend / i.limit) * 100)}%"></i>` : ""}</div>` : ""}
  </div>`;
}

// ---------------------------------------------------------------- suggestions

function suggestItems(q) {
  const ql = lower(q);
  const scored = [];
  for (const it of S.boot.items) {
    const n = lower(it.name);
    let score = -1;
    if (!ql) score = 1;
    else if (n === ql) score = 100;
    else if (n.startsWith(ql)) score = 80;
    else if (n.split(/[\s&\-/]+/).some((w) => w.startsWith(ql))) score = 60;
    else if (n.includes(ql)) score = 40;
    if (score < 0) continue;
    const h = S.boot.hints[it.id];
    scored.push({ it, score: score + Math.min(20, (h ? h.count : 0) / 10) });
  }
  scored.sort((a, b) => b.score - a.score || a.it.name.localeCompare(b.it.name));
  const out = scored.slice(0, 8).map(({ it }) => {
    const left = it.limit === null ? null : it.limit - spentOf(S.month, it.id);
    return { value: it.name, label: it.name, sub: it.category, right: left === null ? "" : left < 0 ? `over ${money(-left)}` : `${money(left)} left`,
      rightClass: left !== null && left < 0 ? "over" : "" };
  });
  if (q.trim() && !S.itemMap.has(ql)) out.push({ value: q.trim(), label: `Create “${q.trim()}”`, create: true });
  return out;
}

function suggestAccounts(q) {
  const ql = lower(q);
  const list = S.boot.accounts.filter((a) => !ql || lower(a.name).includes(ql))
    .sort((a, b) => (lower(a.name).startsWith(ql) ? 0 : 1) - (lower(b.name).startsWith(ql) ? 0 : 1) || a.sort_order - b.sort_order);
  const out = list.slice(0, 8).map((a) => ({ value: a.name, label: a.name }));
  if (q.trim() && !S.accMap.has(ql)) out.push({ value: q.trim(), label: `New account “${q.trim()}”`, create: true });
  return out;
}

function suggestCategories(q) {
  const ql = lower(q);
  const out = S.boot.categories.filter((c) => !ql || lower(c).includes(ql)).slice(0, 8).map((c) => ({ value: c, label: c }));
  if (q.trim() && !S.boot.categories.some((c) => lower(c) === ql)) out.push({ value: q.trim(), label: `New category “${q.trim()}”`, create: true });
  return out;
}

function getOptions(input, q) {
  const k = input.dataset.ac;
  return k === "item" ? suggestItems(q) : k === "account" ? suggestAccounts(q) : suggestCategories(q);
}

// ---------------------------------------------------------------- events

const rowOf = (el) => {
  const tr = el.closest("tr.sr");
  if (!tr) return null;
  return tr.classList.contains("draft") ? S.drafts.find((d) => d.cid === tr.dataset.cid) : S.saved.find((d) => d.cid === tr.dataset.cid);
};

function focusCell(rowCid, field) {
  const tr = $(`tr[data-cid="${rowCid}"]`);
  const inp = tr && $(`[data-f="${field}"]`, tr);
  if (inp) { inp.focus(); inp.select?.(); }
}

function refreshRow(r) {
  const tr = $(`tr[data-cid="${r.cid}"]`);
  if (!tr) return;
  const was = document.activeElement;
  const catCell = $(".c-cat", tr);
  const newItem = isNewItem(r), hasInput = !!$("[data-f=category]", catCell);
  if (newItem !== hasInput) {                         // the category cell switches between a label and an input
    const it = itemInfo(r.item);
    catCell.innerHTML = newItem
      ? `<input data-f="category" data-ac="category" class="newcat" value="${esc(r.category)}" placeholder="New item: category" autocomplete="off">`
      : `<span class="cat-chip">${esc(it ? it.category : "")}</span>`;
  } else if (!newItem) {
    $(".cat-chip", catCell).textContent = itemInfo(r.item)?.category || "";
  }
  $("[data-left]", tr).innerHTML = leftHtml(r.id !== null ? r.limit_left : draftLeft(r));
  $("[data-state]", tr).innerHTML = stateHtml(r);
  ["paid_from", "should_pay"].forEach((f) => {
    const inp = $(`[data-f="${f}"]`, tr);
    if (inp !== was && inp.value !== r[f]) inp.value = r[f];
    inp.classList.toggle("new", !!lower(r[f]) && !S.accMap.has(lower(r[f])));
  });
  const am = $("[data-f=amount]", tr);
  am.placeholder = lastAmountHint(r);
  tr.classList.toggle("incomplete", r.id === null && !blankRow(r) && !complete(r));
  if (r.id === null) {
    // later rows of the same item depend on this one
    S.drafts.forEach((d) => { if (d !== r && lower(d.item) === lower(r.item) && d.kind === "expense") $(`tr[data-cid="${d.cid}"] [data-left]`)?.replaceChildren(...htmlNodes(leftHtml(draftLeft(d)))); });
  }
}

const htmlNodes = (h) => { const t = document.createElement("template"); t.innerHTML = h; return [...t.content.childNodes]; };

function applyItemDefaults(r) {
  const it = itemInfo(r.item);
  if (!it) return;
  r.item = it.name;                                    // use the stored spelling
  const h = S.boot.hints[it.id];
  if (!lower(r.should_pay) || r.auto.should_pay) { r.should_pay = it.account || r.should_pay; r.auto.should_pay = true; }
  if (!lower(r.paid_from) || r.auto.paid_from) {
    r.paid_from = (h && h.paid_from_id && S.boot.accounts.find((a) => a.id === h.paid_from_id)?.name) || it.account || r.paid_from;
    r.auto.paid_from = true;
  }
  if (h && h.kind === "income" && r.kind === "expense" && !r.amount) r.kind = "income";
}

function onInput(e) {
  const inp = e.target.closest("[data-f]");
  const r = inp && rowOf(inp);
  if (!r) return;
  const f = inp.dataset.f;
  if (f === "date") { r.dateText = inp.value; return; }
  r[f] = inp.value;
  r.dirty = true;
  if (f === "paid_from" || f === "should_pay") r.auto[f] = false;
  if (f === "item" && itemInfo(r.item) && e.type === "input" && e.target.dataset.picked) delete e.target.dataset.picked;
  if (r.id === null) {
    const last = S.drafts[S.drafts.length - 1];
    if (r === last && !blankRow(r)) addDraft();
    saveDrafts();
    updateCounts();
    renderTotals();
  }
  refreshRow(r);
  renderSide();
}

function addDraft() {
  const d = blank();
  S.drafts.push(d);
  $("#new-grid tbody").insertAdjacentHTML("beforeend", rowHtml(d));
  return d;
}

function commitDate(inp, r) {
  const t = inp.value;
  const iso = parseDate(t);
  inp.classList.toggle("bad", iso === null);
  if (iso === null) { r.dateBad = true; return; }
  r.dateBad = false;
  const changed = iso !== r.date;
  r.date = iso;
  inp.value = fmtDate(iso);
  if (changed) { r.dirty = true; if (r.id === null) { ensureSpent([monthOf(iso)]).then(() => { refreshRow(r); renderSide(); }); saveDrafts(); } }
}

async function ensureSpent(months) {
  const need = months.filter((m) => !S.spent[m]);
  if (!need.length) return;
  const got = await api.sheetSpent(need);
  Object.assign(S.spent, got);
}

function onFocusOut(e) {
  const inp = e.target.closest("[data-f]");
  if (!inp) return;
  const r = rowOf(inp);
  if (!r) return;
  if (inp.dataset.f === "date") commitDate(inp, r);
  if (inp.dataset.f === "item" && itemInfo(r.item)) {                // typed an existing name: fill category, accounts
    const before = JSON.stringify([r.should_pay, r.paid_from]);
    applyItemDefaults(r);
    if (before !== JSON.stringify([r.should_pay, r.paid_from]) || inp.value !== r.item) { inp.value = r.item; refreshRow(r); renderSide(); }
  }
  const tr = inp.closest("tr");
  setTimeout(() => {
    if (tr.contains(document.activeElement) || document.querySelector(".ac-pop:hover")) return;     // still inside the same row
    rowLeft(r);
  }, 0);
}

function onPick(e) {
  const inp = e.target.closest("[data-f]");
  const r = inp && rowOf(inp);
  if (!r) return;
  if (inp.dataset.f === "item") {
    applyItemDefaults(r);
    refreshRow(r);
    renderSide();
    // Enter or a click jumps to the amount (what is still missing); Tab moves on by itself
    if (e.detail.key !== "Tab") focusCell(r.cid, num(r.amount) ? "paid_from" : "amount");
  }
}

async function rowLeft(r) {
  if (r.dateBad) return;
  if (r.id === null) {
    if (S.autosave && complete(r) && !needsConfirm(r) && r.status !== "saving" && r.status !== "error") await saveRows([r], { silent: true });
    return;
  }
  if (!r.dirty || !S.editable) return;
  if (!complete(r)) { r.status = "error"; r.error = "Date, item and amount are needed"; refreshRow(r); return; }
  if (needsConfirm(r)) {
    const bits = [isNewItem(r) ? `item “${r.item.trim()}”` : null, ...newAccounts(r).map((a) => `account “${a.trim()}”`)].filter(Boolean);
    if (!(await confirmDialog("Create something new?", `This adds the ${bits.join(" and ")} to your lists. Check the spelling first.`, "Create and save"))) return;
  }
  r.status = "saving"; refreshRow(r);
  try {
    await api.sheetUpdate(r.id, payload(r));
    r.dirty = false; r.status = ""; r.error = "";
    toast("Updated");
    await afterChange();
  } catch (err) {
    r.status = "error"; r.error = err.message; refreshRow(r);
  }
}

/** Saved rows can change each other's "limit left"; refresh the numbers without touching what is being typed. */
async function afterChange() {
  const focus = document.activeElement && document.activeElement.closest?.("tr")?.dataset.cid;
  await loadMonth(true);
  S.saved.forEach((r) => {
    const tr = $(`tr[data-cid="${r.cid}"]`);
    if (tr && !tr.classList.contains("saving")) $("[data-left]", tr).innerHTML = leftHtml(r.limit_left);
  });
  if (!S.search) $("#saved-empty").classList.toggle("hidden", S.saved.length > 0);
  S.drafts.forEach(refreshRow);
  if (focus) $(`tr[data-cid="${focus}"] :focus`);
}

async function saveRows(rowsToSave, { silent = false } = {}) {
  rowsToSave.forEach((r) => { r.status = "saving"; refreshRow(r); });
  S.busy = true; updateCounts();
  let res;
  try {
    res = await api.sheetBulk(rowsToSave.map((r) => ({ ...payload(r), client_id: r.cid })));
  } catch (err) {
    rowsToSave.forEach((r) => { r.status = "error"; r.error = err.message; refreshRow(r); });
    S.busy = false; updateCounts();
    return;
  }
  const ok = new Set(res.saved.map((s) => s.client_id));
  res.errors.forEach((er) => { const r = S.drafts.find((d) => d.cid === er.client_id); if (r) { r.status = "error"; r.error = er.error; refreshRow(r); } });
  // take the saved rows out of the grid without redrawing it: the next row may be being typed in right now
  ok.forEach((c) => $(`#new-grid tr[data-cid="${c}"]`)?.remove());
  S.drafts = S.drafts.filter((d) => !ok.has(d.cid));
  if (!S.drafts.some(blankRow)) { const d = blank(); S.drafts.push(d); $("#new-grid tbody").insertAdjacentHTML("beforeend", rowHtml(d)); }
  S.busy = false;
  saveDrafts();
  S.spent = {};                                   // forget cached month totals; they changed
  await loadMonth(true);
  renderSaved();
  S.drafts.forEach(refreshRow);
  const months = [...new Set(S.drafts.map((d) => monthOf(d.date)).filter((m) => m !== S.month))];
  if (months.length) { await ensureSpent(months); S.drafts.forEach(refreshRow); }
  if (res.saved.length) toast(silent ? `Saved · ${res.saved[0].entry.item}` : `Saved ${res.saved.length} ${res.saved.length === 1 ? "entry" : "entries"}`);
  if (res.errors.length) toast(`${res.errors.length} row${res.errors.length > 1 ? "s" : ""} couldn't be saved: see the red rows`, true);
  updateCounts();
}

async function saveAll() {
  const ready = S.drafts.filter((d) => complete(d) && d.status !== "saving");
  if (!ready.length) { toast("Nothing to save yet: each row needs a date, item and amount", true); return; }
  const items = [...new Set(ready.filter(isNewItem).map((r) => r.item.trim()))];
  const accs = [...new Set(ready.flatMap(newAccounts).map((a) => a.trim()))];
  if (items.length || accs.length) {
    const ok = await confirmDialog("Create new items or accounts?",
      `${items.length ? `New items: ${items.join(", ")}. ` : ""}${accs.length ? `New accounts: ${accs.join(", ")}. ` : ""}Check the spelling: a typo here would create a duplicate.`, "Create and save");
    if (!ok) return;
  }
  await saveRows(ready);
}

function onKeyDown(e) {
  const inp = e.target.closest("[data-f]");
  const tr = e.target.closest("tr.sr");
  if (!inp || !tr) return;
  const r = rowOf(inp);
  if ((e.ctrlKey || e.metaKey) && (e.key === "Enter" || e.key.toLowerCase() === "s")) { e.preventDefault(); saveAll(); return; }
  const f = inp.dataset.f;
  if (f === "date" && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
    const base = parseDate(inp.value) || r.date || todayISO();
    const iso = shiftISO(base, e.key === "ArrowUp" ? 1 : -1);
    inp.value = fmtDate(iso);
    commitDate(inp, r);
    e.preventDefault();
    return;
  }
  if (e.defaultPrevented) return;
  const order = $$("[data-f]", tr).filter((x) => !x.readOnly);
  const i = order.indexOf(inp);
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (i < order.length - 1) { order[i + 1].focus(); order[i + 1].select?.(); }
    else nextRow(tr, r);
  } else if (e.key === "Tab" && !e.shiftKey && i === order.length - 1 && r.id === null) {
    if (S.drafts[S.drafts.length - 1] === r) { e.preventDefault(); const d = addDraft(); focusCell(d.cid, "item"); }
  } else if (e.key === "Escape" && r.id !== null && r.dirty) {
    renderSaved();                                  // throw away edits to this saved row
  }
}

function nextRow(tr, r) {
  const grid = tr.closest("tbody");
  let nxt = tr.nextElementSibling;
  if (!nxt && r.id === null) { const d = addDraft(); nxt = $(`tr[data-cid="${d.cid}"]`); }
  if (nxt) { const f = $("[data-f=item]", nxt); f.focus(); f.select?.(); }
  else grid.closest("section").scrollIntoView({ block: "nearest" });
}

async function onClick(e) {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const r = rowOf(b);
  if (!r) return;
  if (b.dataset.act === "kind") {
    r.kind = r.kind === "income" ? "expense" : "income";
    b.className = `kind ${r.kind}`; b.textContent = r.kind === "income" ? "In" : "Out";
    const tr = b.closest("tr");
    $("[data-f=paid_from]", tr).placeholder = r.kind === "income" ? "Received in" : "Paid from";
    $("[data-f=should_pay]", tr).placeholder = r.kind === "income" ? "Belongs to" : "Should pay";
    r.dirty = true;
    refreshRow(r); renderSide(); renderTotals();
    if (r.id !== null) rowLeft(r); else saveDrafts();
  } else if (b.dataset.act === "del") {
    if (r.id === null) {
      S.drafts = S.drafts.filter((d) => d !== r);
      if (!S.drafts.some(blankRow)) S.drafts.push(blank());
      saveDrafts(); renderDrafts(); renderSide(); renderTotals();
    } else if (await confirmDialog("Delete this entry?", `${fmtDate(r.date)} · ${r.item} · ${money(num(r.amount))}`)) {
      try { await api.sheetDelete(r.id); toast("Deleted"); S.spent = {}; await loadMonth(); } catch (err) { toast(err.message, true); }
    }
  }
}

// ---- paste rows from Excel
const HEAD_MAP = { date: "date", item: "item", masteritems: "item", masteritem: "item", category: "category", amount: "amount", paidfrom: "paid_from",
  shouldpay: "should_pay", note: "note", type: "kind" };

function parsePaste(text) {
  const rows = text.replace(/\r/g, "").split("\n").filter((l) => l.trim()).map((l) => l.split("\t"));
  if (!rows.length) return [];
  const norm = (s) => s.toLowerCase().replace(/[^a-z]/g, "");
  let map = rows[0].map((h) => HEAD_MAP[norm(h)]);
  let body = rows;
  if (map.includes("date") && map.includes("item")) body = rows.slice(1);
  else map = rows[0].length >= 7 ? ["date", "item", "category", "amount", null, "paid_from", "should_pay"]
    : ["date", "item", "amount", "paid_from", "should_pay", "note"];
  return body.map((cells) => {
    const r = blank();
    map.forEach((f, i) => {
      if (!f || cells[i] === undefined) return;
      const v = cells[i].trim();
      if (f === "date") { const iso = parseDate(v) ?? parseExcelDate(v); if (iso) r.date = iso; }
      else if (f === "kind") r.kind = /^in|cr/i.test(v) ? "income" : "expense";
      else if (f === "amount") r.amount = String(Math.abs(num(v)) || "");
      else r[f] = v;
    });
    return r;
  }).filter((r) => lower(r.item) || r.amount);
}

function parseExcelDate(v) {
  const m = v.match(/^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})$/);
  if (!m) return null;
  const mi = MON.findIndex((x) => m[1].toLowerCase().startsWith(x.toLowerCase())) + 1;
  return mi ? isoOk(+m[3], mi, +m[2]) : null;
}

function onPaste(e) {
  const inp = e.target.closest("[data-f]");
  if (!inp || !inp.closest("#new-grid")) return;
  const text = (e.clipboardData || window.clipboardData).getData("text");
  if (!/[\t\n]/.test(text.trim())) return;               // a single value pastes normally
  e.preventDefault();
  const rows = parsePaste(text);
  if (!rows.length) { toast("Couldn't find rows in what you pasted. Include the heading row from Excel.", true); return; }
  rows.forEach((r) => {
    const it = itemInfo(r.item);
    if (it) { r.item = it.name; r.auto = { paid_from: !r.paid_from, should_pay: !r.should_pay }; if (!r.should_pay) r.should_pay = it.account || ""; }
  });
  S.drafts = S.drafts.filter((d) => !blankRow(d)).concat(rows, [blank()]);
  saveDrafts(); renderDrafts(); renderSide(); renderTotals();
  toast(`${rows.length} row${rows.length > 1 ? "s" : ""} pasted. Check them, then Save all.`);
}

function bind() {
  const root = $("#sheet-root");
  attachAutosuggest(root, getOptions);                 // first, so Enter/Tab accept a suggestion before the sheet moves on
  root.addEventListener("input", onInput);
  root.addEventListener("focusout", onFocusOut);
  root.addEventListener("keydown", onKeyDown);
  root.addEventListener("click", onClick);
  root.addEventListener("paste", onPaste);
  root.addEventListener("ac:pick", onPick);
  root.addEventListener("focusin", (e) => { if (e.target.matches?.("[data-f=date]")) e.target.select(); });

  const go = (m) => { S.month = m; S.search = ""; S.spent = {}; $("#search").value = ""; $("#m-pick").innerHTML = monthPicker("m-input", S.month); bindMonthPicker($("#m-input")); bindMonth(); loadMonth(); };
  const bindMonth = () => $("#m-input").addEventListener("change", (e) => e.target.value && go(e.target.value));
  bindMonth();
  $("#m-prev").onclick = () => go(shiftMonth(S.month, -1));
  $("#m-next").onclick = () => go(shiftMonth(S.month, 1));
  let t;
  $("#search").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { S.search = e.target.value.trim(); loadMonth(); }, 250); });
  $("#save-all")?.addEventListener("click", saveAll);
  $("#autosave")?.addEventListener("change", (e) => { S.autosave = e.target.checked; });
  window.onbeforeunload = () => (S.drafts.some((d) => !blankRow(d)) ? "You have entries that are not saved yet." : undefined);
  window.addEventListener("hashchange", () => { window.onbeforeunload = null; closeSuggestions(); }, { once: true });
}
