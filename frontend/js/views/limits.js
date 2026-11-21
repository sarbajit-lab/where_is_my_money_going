// Items & limits: the master list (what the old Properties tab was). Category, monthly limit, usual account,
// and what has been spent and is left this month. Edit a cell, press Enter or leave the row: it saves.
import { api } from "../api.js";
import { attachAutosuggest } from "../ac.js";
import { can } from "../state.js";
import { $, $$, bindMonthPicker, confirmDialog, esc, money, monthLabel, monthPicker, shiftMonth, thisMonth, toast } from "../util.js";

let month = thisMonth();
let data = null;
let filter = "";

export async function render(params = {}) {
  if (params.month) month = params.month;
  data = await api.sheetItems(month);
  draw();
}

const editable = () => can("masters.write");

function draw() {
  const ed = editable();
  const q = filter.toLowerCase();
  const items = data.items.filter((i) => !q || i.name.toLowerCase().includes(q) || i.category.toLowerCase().includes(q));
  const groups = {};
  items.forEach((i) => (groups[i.category] ||= []).push(i));
  const tot = items.filter((i) => i.active).reduce((a, i) => ({ spent: a.spent + i.spent, limit: a.limit + (i.limit || 0) }), { spent: 0, limit: 0 });
  $("#view").innerHTML = `<div id="limits-root">
    <div class="page-head"><div><h1>Items &amp; limits</h1>
      <div class="sub small muted">The master list: category, monthly limit and the account that should normally pay. “Spent” and “Left” are for the month you pick.</div></div>
      <div class="toolbar"><div class="month-nav"><button class="btn btn-icon" id="m-prev">‹</button><div id="m-pick">${monthPicker("m-input", month)}</div><button class="btn btn-icon" id="m-next">›</button></div>
        <input type="search" id="flt" placeholder="Filter items…" value="${esc(filter)}" style="max-width:200px"></div></div>
    <div class="totals-strip"><div class="ts-item"><span class="ts-k">Items</span><span class="ts-v">${data.items.filter((i) => i.active).length}</span></div>
      <div class="ts-item"><span class="ts-k">Spent in ${esc(monthLabel(month))}</span><span class="ts-v c-expense">${money(tot.spent)}</span></div>
      <div class="ts-item"><span class="ts-k">Limits add up to</span><span class="ts-v">${money(tot.limit)}</span></div></div>
    <div class="grid grid-main">
      <div class="stack">
      ${Object.keys(groups).sort((a, b) => a.localeCompare(b)).map((cat) => `
        <section class="panel"><div class="panel-head"><h2>${esc(cat)}</h2>
          <span class="small faint">${money(groups[cat].reduce((a, i) => a + i.spent, 0))} spent</span></div>
          <div class="table-wrap"><table class="master-table lim-table"><thead><tr><th>Item</th><th>Category</th><th class="num">Monthly limit</th>
            <th class="num">Spent</th><th class="num">Left</th><th>Account (should pay)</th><th>Active</th><th></th></tr></thead><tbody>
          ${groups[cat].map((i) => row(i, ed)).join("")}</tbody></table></div></section>`).join("") || `<div class="panel empty">No items yet. Add one on the right, or import your Excel sheet.</div>`}
      </div>
      <div class="stack">
        ${ed ? `<section class="panel panel-pad"><h2>Add an item</h2>
          <form id="add-item" class="stack" novalidate style="margin-top:10px">
            <div class="field"><label class="req">Item</label><input name="name" maxlength="80" required></div>
            <div class="field"><label>Category</label><input name="category" data-ac="category" placeholder="e.g. Utility"></div>
            <div class="field"><label>Monthly limit (blank = no limit)</label><input name="limit" inputmode="decimal"></div>
            <div class="field"><label>Account that should pay</label><input name="account" data-ac="account"></div>
            <div><button class="btn btn-primary">Add item</button></div></form></section>` : ""}
        <section class="panel panel-pad"><h2>Accounts</h2>
          <p class="small muted" style="margin:4px 0 8px">Names used in “Paid from” and “Should pay”.</p>
          <table class="master-table"><tbody>${data.accounts.map((a) => `<tr data-aid="${a.id}" class="${a.active ? "" : "inactive"}">
            <td><input type="text" data-af="name" value="${esc(a.name)}" ${ed ? "" : "readonly"}></td>
            <td class="small muted num">${a.used}</td>
            <td>${ed ? `<input type="checkbox" data-af="active" ${a.active ? "checked" : ""} title="Active">` : ""}</td>
            <td>${ed && !a.used && !a.items ? `<button class="btn btn-sm btn-ghost btn-danger" data-adel="${a.id}">✕</button>` : ""}</td></tr>`).join("")}</tbody></table>
          ${ed ? `<form id="add-acc" class="add-row"><input type="text" name="name" placeholder="New account" maxlength="80" required><button class="btn btn-primary">Add</button></form>` : ""}
        </section>
      </div></div></div>`;
  bind();
}

function row(i, ed) {
  const ro = ed ? "" : "readonly";
  const cls = i.left !== null && i.left < 0 ? "neg" : "";
  return `<tr data-id="${i.id}" class="${i.active ? "" : "inactive"}">
    <td><input type="text" data-f="name" value="${esc(i.name)}" ${ro}></td>
    <td><input type="text" data-f="category" data-ac="category" value="${esc(i.category)}" ${ro}></td>
    <td class="num"><input type="text" data-f="limit" inputmode="decimal" value="${i.limit === null ? "" : i.limit}" placeholder="none" ${ro}></td>
    <td class="num">${money(i.spent)}</td>
    <td class="num ${cls}">${i.left === null ? `<span class="faint">—</span>` : (i.left < 0 ? `<b class="c-expense">${money(i.left)}</b>` : money(i.left))}</td>
    <td><input type="text" data-f="account" data-ac="account" value="${esc(i.account || "")}" ${ro}></td>
    <td>${ed ? `<input type="checkbox" data-f="active" ${i.active ? "checked" : ""}>` : (i.active ? "✓" : "")}</td>
    <td style="white-space:nowrap">${ed ? `<button class="btn btn-sm" data-save="${i.id}">Save</button>${i.used ? "" : `<button class="btn btn-sm btn-ghost btn-danger" data-del="${i.id}">✕</button>`}` : ""}</td></tr>`;
}

function bind() {
  const root = $("#limits-root");
  const go = (m) => { month = m; render(); };
  $("#m-prev").onclick = () => go(shiftMonth(month, -1));
  $("#m-next").onclick = () => go(shiftMonth(month, 1));
  bindMonthPicker($("#m-input"));
  $("#m-input").addEventListener("change", (e) => e.target.value && go(e.target.value));
  $("#flt").addEventListener("input", (e) => { filter = e.target.value; const pos = e.target.selectionStart; draw(); const f = $("#flt"); f.focus(); f.setSelectionRange(pos, pos); });
  if (!editable()) return;
  attachAutosuggest(root, (input, q) => {
    const ql = q.toLowerCase();
    const list = input.dataset.ac === "account" ? data.accounts.map((a) => a.name) : data.categories;
    return list.filter((x) => !ql || x.toLowerCase().includes(ql)).slice(0, 8).map((x) => ({ value: x, label: x }));
  });
  const save = async (tr) => {
    const g = (f) => $(`[data-f="${f}"]`, tr);
    try {
      await api.sheetItemSave(+tr.dataset.id, { name: g("name").value, category: g("category").value, limit: g("limit").value,
        account: g("account").value, active: g("active").checked });
      toast("Saved"); render();
    } catch (e) { toast(e.message, true); }
  };
  $$("[data-save]", root).forEach((b) => b.addEventListener("click", () => save(b.closest("tr"))));
  $$("tr[data-id] input[type=text]", root).forEach((inp) => inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(inp.closest("tr")); } }));
  $$("[data-del]", root).forEach((b) => b.addEventListener("click", async () => {
    if (!(await confirmDialog("Delete this item?", "It has no entries, so nothing else changes."))) return;
    try { await api.sheetItemDelete(+b.dataset.del); render(); } catch (e) { toast(e.message, true); }
  }));
  $("#add-item")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target).entries());
    try { await api.sheetItemAdd(f); toast("Item added"); render(); } catch (err) { toast(err.message, true); }
  });
  $("#add-acc")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api.sheetAccountAdd({ name: new FormData(e.target).get("name") }); toast("Account added"); render(); } catch (err) { toast(err.message, true); }
  });
  $$("tr[data-aid]", root).forEach((tr) => {
    const upd = async () => {
      try { await api.sheetAccountSave(+tr.dataset.aid, { name: $("[data-af=name]", tr).value, active: $("[data-af=active]", tr).checked }); toast("Saved"); render(); }
      catch (e) { toast(e.message, true); }
    };
    $("[data-af=name]", tr).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); upd(); } });
    $("[data-af=name]", tr).addEventListener("change", upd);
    $("[data-af=active]", tr).addEventListener("change", upd);
  });
  $$("[data-adel]", root).forEach((b) => b.addEventListener("click", async () => {
    try { await api.sheetAccountDelete(+b.dataset.adel); render(); } catch (e) { toast(e.message, true); }
  }));
}
