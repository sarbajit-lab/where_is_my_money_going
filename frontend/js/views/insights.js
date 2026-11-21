// Insights: where the money went, limit use, and who owes whom (paid from vs should pay). All worked out on this computer.
import { api } from "../api.js";
import { barList, incomeExpenseChart } from "../charts.js";
import { $, esc, financialYear, money, monthLabel, shiftMonth, store, thisMonth } from "../util.js";

const PRESETS = {
  this: "This month", last: "Last month", "3m": "Last 3 months", fy: "This financial year (Apr–Mar)",
  "12m": "Last 12 months", all: "All time",
};

function range(preset) {
  const cur = thisMonth();
  const end = (m) => { const [y, mo] = m.split("-").map(Number); return `${m}-${String(new Date(y, mo, 0).getDate()).padStart(2, "0")}`; };
  if (preset === "this") return { from: `${cur}-01`, to: end(cur), limit_month: cur };
  if (preset === "last") { const m = shiftMonth(cur, -1); return { from: `${m}-01`, to: end(m), limit_month: m }; }
  if (preset === "3m") return { from: `${shiftMonth(cur, -2)}-01`, to: end(cur), limit_month: cur };
  if (preset === "12m") return { from: `${shiftMonth(cur, -11)}-01`, to: end(cur), limit_month: cur };
  if (preset === "fy") { const f = financialYear(); return { from: f.from, to: f.to, limit_month: cur }; }
  if (/^\d{4}-\d{2}$/.test(preset)) return { from: `${preset}-01`, to: end(preset), limit_month: preset };
  return { limit_month: cur };
}

export async function render(params = {}) {
  const preset = params.r || store.get("insights-range", "this");
  store.set("insights-range", preset);
  const d = await api.insights(range(preset));
  const t = d.totals;
  const total = d.by_category.reduce((a, c) => a + c.value, 0) || 1;
  const maxM = Math.max(1, ...Object.values(d.grid.reduce((a, g) => ((a[g.name] = (a[g.name] || 0) + g.value), a), {})));
  $("#view").innerHTML = `
    <div class="page-head"><div><h1>Insights</h1><div class="sub small muted">${d.range.first_entry ? `Entries from ${esc(d.range.first_entry)} to ${esc(d.range.last_entry)}` : "No entries in this period"}</div></div>
      <div class="toolbar"><select id="range">${Object.entries(PRESETS).map(([k, l]) => `<option value="${k}" ${k === preset ? "selected" : ""}>${l}</option>`).join("")}
        ${/^\d{4}-\d{2}$/.test(preset) ? `<option value="${preset}" selected>${esc(monthLabel(preset))}</option>` : ""}</select>
        <input type="month" id="pick-month" value="${/^\d{4}-\d{2}$/.test(preset) ? preset : ""}" title="Pick one month"></div></div>
    <div class="grid grid-4">
      <div class="panel kpi"><div class="kpi-label">Spent</div><div class="kpi-value c-expense">${money(t.expense)}</div></div>
      <div class="panel kpi"><div class="kpi-label">Received</div><div class="kpi-value c-income">${money(t.income)}</div></div>
      <div class="panel kpi"><div class="kpi-label">Net</div><div class="kpi-value ${t.net < 0 ? "c-expense" : "c-income"}">${money(t.net, { sign: true })}</div></div>
      <div class="panel kpi"><div class="kpi-label">Entries</div><div class="kpi-value">${t.entries.toLocaleString("en-IN")}</div></div>
    </div>
    <section class="panel" style="margin-top:16px"><div class="panel-head"><h2>Month by month</h2>
      <div class="legend"><span><i style="background:var(--income)"></i>Received</span><span><i style="background:var(--expense)"></i>Spent</span></div></div>
      <div class="panel-body chart" id="trend"></div></section>
    <div class="grid grid-2" style="margin-top:16px">
      <section class="panel"><div class="panel-head"><h2>Spending by category</h2></div><div class="panel-body" id="cats"></div></section>
      <section class="panel"><div class="panel-head"><h2>Biggest items</h2></div><div class="panel-body" id="items"></div></section>
    </div>
    <div class="grid grid-2" style="margin-top:16px">
      <section class="panel"><div class="panel-head"><h2>Limits · ${esc(monthLabel(d.limits.month))}</h2></div><div class="panel-body" id="limits"></div></section>
      <section class="panel"><div class="panel-head"><h2>Went over the limit most</h2><span class="small faint">months over, in this period</span></div>
        <div class="panel-body" id="over"></div></section>
    </div>
    <section class="panel" style="margin-top:16px"><div class="panel-head"><h2>Who owes whom</h2>
      <span class="small faint">Paid from vs should pay, netted per pair of accounts</span></div>
      <div class="panel-body"><div class="grid grid-2">
        <div id="settle"></div>
        <div id="flow"></div></div></div></section>
    <section class="panel" style="margin-top:16px"><div class="panel-head"><h2>Month × category</h2></div>
      <div class="table-wrap"><table class="heat" id="heat"></table></div></section>`;

  incomeExpenseChart($("#trend"), d.monthly.map((m) => ({ ...m, net: m.income - m.expense })));
  barList($("#cats"), d.by_category.map((c) => ({ name: c.name, amount: c.value, share: Math.round((c.value / total) * 100) })), { empty: "No spending in this period" });
  barList($("#items"), d.by_item.slice(0, 12).map((i) => ({ name: i.name, amount: i.value })), { kind: "neutral", showShare: false, empty: "No spending in this period" });
  $("#limits").innerHTML = d.limits.items.length ? `<div class="bars">${d.limits.items.slice(0, 14).map((i) => {
    const pct = Math.min(100, (i.spent / i.limit) * 100);
    return `<div class="bar-row"><span class="name">${esc(i.name)}</span>
      <span class="val ${i.left < 0 ? "c-expense" : ""}">${i.left < 0 ? `over ${money(-i.left)}` : `${money(i.left)} left`}</span>
      <div class="bar-track"><div class="bar-fill ${i.left < 0 ? "" : "neutral"}" style="width:${Math.max(1, pct)}%;${i.left < 0 ? "background:var(--expense)" : ""}"></div></div></div>`;
  }).join("")}</div>` : `<div class="empty small">No items with a monthly limit yet.</div>`;
  $("#over").innerHTML = d.overspent.length ? `<table><tbody>${d.overspent.map((o) => `<tr><td>${esc(o.name)}<div class="cell-sub">${esc(o.category)}</div></td>
    <td class="num">${o.months} month${o.months > 1 ? "s" : ""}</td><td class="num c-expense">${money(o.over)}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty small">Nothing went over its limit in this period.</div>`;
  $("#settle").innerHTML = d.settlement.transfers.length ? `<h3 style="margin-bottom:8px">To settle up</h3><table><tbody>${d.settlement.transfers.map((x) =>
    `<tr><td><b>${esc(x.from)}</b> <span class="muted">should pay</span> <b>${esc(x.to)}</b></td><td class="num">${money(x.amount)}</td></tr>`).join("")}</tbody></table>
    <p class="small faint" style="margin:8px 0 0">An account is “owed” when it paid for something another account should have paid.</p>`
    : `<div class="empty small">Everything was paid from the account that should pay.</div>`;
  $("#flow").innerHTML = d.accounts.length ? `<h3 style="margin-bottom:8px">By account</h3><table><thead><tr><th>Account</th><th class="num">Paid</th><th class="num">Should pay</th></tr></thead><tbody>${d.accounts.map((a) =>
    `<tr><td>${esc(a.name)}</td><td class="num">${money(a.paid)}</td><td class="num">${money(a.should_pay)}</td></tr>`).join("")}</tbody></table>` : "";
  const months = [...new Set(d.grid.map((g) => g.month))].sort();
  const cats = d.by_category.map((c) => c.name);
  const val = (m, c) => (d.grid.find((g) => g.month === m && g.name === c) || {}).value || 0;
  $("#heat").innerHTML = months.length ? `<thead><tr><th>Category</th>${months.map((m) => `<th class="num">${esc(m)}</th>`).join("")}</tr></thead><tbody>${cats.map((c) =>
    `<tr><td>${esc(c)}</td>${months.map((m) => { const v = val(m, c); return `<td class="num ${v ? "" : "zero"}">${v ? `<span style="background:color-mix(in srgb, var(--brand) ${Math.round((v / maxM) * 55)}%, transparent)">${money(v)}</span>` : "·"}</td>`; }).join("")}</tr>`).join("")}</tbody>` : `<tbody><tr><td class="empty small">Nothing yet</td></tr></tbody>`;
  $("#range").addEventListener("change", (e) => { location.hash = `#/insights?r=${e.target.value}`; });
  $("#pick-month").addEventListener("change", (e) => { if (e.target.value) location.hash = `#/insights?r=${e.target.value}`; });
}
