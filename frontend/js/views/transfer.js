// Import and export: bring a spreadsheet in (Excel .xlsx, CSV, or paste from Excel) and take everything out in the same layout.
import { api, qs } from "../api.js";
import { can } from "../state.js";
import { $, esc, money, monthPicker, bindMonthPicker, thisMonth, toast } from "../util.js";

export async function render() {
  const month = thisMonth();
  $("#view").innerHTML = `<div id="tr-root">
    <div class="page-head"><div><h1>Import &amp; export</h1>
      <div class="sub small muted">Same layout as your spreadsheet: Date, Item, Category, Amount, Limit Left, Paid From, Should Pay. Nothing leaves this computer.</div></div></div>
    <div class="grid grid-2">
      ${can("data.import") ? `<section class="panel panel-pad"><h2>Import</h2>
        <p class="small muted" style="margin:6px 0 12px">An Excel file can hold both tabs: the <b>Properties</b> tab (Master Items, Category, Limit, Account) and the
          <b>Transactions</b> tab. Many years at once is fine. Rows already in WIMMG are skipped, so importing the same file twice is safe.</p>
        <form id="imp" class="stack" novalidate>
          <div class="field"><label>Excel (.xlsx) or CSV file</label><input type="file" name="file" id="imp-file" accept=".xlsx,.xlsm,.csv,.tsv,.txt"></div>
          <div class="field"><label>…or paste rows copied from Excel (with the heading row)</label>
            <textarea name="text" id="imp-text" rows="5" placeholder="Date&#9;Item&#9;Category&#9;Amount&#9;Limit Left&#9;Paid From&#9;Should Pay"></textarea></div>
          <label class="small"><input type="checkbox" id="imp-skip" checked> Skip rows that are already in WIMMG</label>
          <div class="toolbar"><button class="btn" id="imp-check" type="submit">Check file</button>
            <a class="small" href="/api/sheet/template.csv">Download a blank template</a></div>
        </form><div id="imp-result" style="margin-top:14px"></div></section>` : `<section class="panel panel-pad"><h2>Import</h2><p class="muted small">Your role can't import files.</p></section>`}
      ${can("data.export") ? `<section class="panel panel-pad"><h2>Export</h2>
        <p class="small muted" style="margin:6px 0 12px">Excel file with a <b>Transactions</b> tab and a <b>Properties</b> tab (spent and limit left for the chosen month).</p>
        <form id="exp" class="stack" novalidate>
          <div class="form-grid"><div class="field"><label>From date</label><input type="date" name="from"></div>
            <div class="field"><label>To date</label><input type="date" name="to"></div></div>
          <div class="field"><label>Properties tab month</label><div>${monthPicker("exp-month", month)}</div></div>
          <p class="small faint" style="margin:0">Leave the dates empty to export everything. Extra columns <b>Type</b> and <b>Note</b> are added at the end.</p>
          <div class="toolbar"><button class="btn btn-primary" data-k="xlsx" type="button">Download Excel</button>
            <button class="btn" data-k="csv" type="button">Transactions CSV</button>
            <button class="btn" data-k="props" type="button">Properties CSV</button></div></form></section>` : ""}
    </div></div>`;
  bindMonthPicker($("#exp-month"));
  const exp = $("#exp");
  exp?.addEventListener("click", (e) => {
    const k = e.target.dataset.k;
    if (!k) return;
    const f = Object.fromEntries(new FormData(exp).entries());
    const p = { from: f.from, to: f.to, month: $("#exp-month").value };
    location.href = k === "xlsx" ? api.exportUrl2("xlsx", p) : k === "csv" ? api.exportUrl2("csv", p) : api.exportUrl2("csv", { ...p, what: "properties" });
  });
  const form = $("#imp");
  if (!form) return;
  const formData = () => {
    const fd = new FormData();
    const file = $("#imp-file").files[0];
    if (file) fd.append("file", file); else fd.append("text", $("#imp-text").value);
    fd.append("skip_duplicates", $("#imp-skip").checked ? "1" : "0");
    return fd;
  };
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $("#imp-result");
    out.innerHTML = `<div class="loading">Reading…</div>`;
    try { showPreview(out, await api.importPreview(formData()), formData); } catch (err) { out.innerHTML = `<p class="callout loss small">${esc(err.message)}</p>`; }
  });
}

function showPreview(out, p, formData) {
  const list = (a) => (a.length ? esc(a.slice(0, 12).join(", ")) + (a.length > 12 ? ` and ${a.length - 12} more` : "") : "none");
  out.innerHTML = `<div class="callout"><b>This file contains</b>
    <ul class="small" style="margin:6px 0 0;padding-left:18px">
      ${p.transactions ? `<li><b>${p.transactions.toLocaleString("en-IN")}</b> transactions (${esc(p.first_date)} → ${esc(p.last_date)}): <b>${p.new_transactions.toLocaleString("en-IN")}</b> new, ${p.duplicates.toLocaleString("en-IN")} already in WIMMG${p.income_rows ? `, ${p.income_rows} income` : ""}</li>` : ""}
      ${p.properties ? `<li><b>${p.properties}</b> items with limits and accounts (their category, limit and account are updated)</li>` : ""}
      <li>New items to be created: ${list(p.new_items)}</li>
      <li>New accounts to be created: ${list(p.new_accounts)}</li>
      ${p.skipped_sheets.length ? `<li class="muted">Tabs ignored (no table found): ${esc(p.skipped_sheets.join(", "))}</li>` : ""}</ul></div>
    ${p.issue_count ? `<div class="callout warn small" style="margin-top:10px"><b>${p.issue_count} row${p.issue_count > 1 ? "s" : ""} can't be imported</b> and will be left out:
      <ul style="margin:6px 0 0;padding-left:18px">${p.issues.slice(0, 8).map((i) => `<li>${esc(i.sheet)} row ${i.line}: ${esc(i.error)}</li>`).join("")}</ul></div>` : ""}
    ${p.sample.length ? `<div class="table-wrap" style="margin-top:10px"><table class="small"><thead><tr><th>Date</th><th>Item</th><th>Category</th><th class="num">Amount</th><th>Paid from</th><th>Should pay</th></tr></thead><tbody>
      ${p.sample.map((r) => `<tr class="${r.duplicate ? "inactive" : ""}"><td>${esc(r.date)}</td><td>${esc(r.item)}</td><td>${esc(r.category)}</td><td class="num">${money(r.amount)}</td><td>${esc(r.paid_from)}</td><td>${esc(r.should_pay)}${r.duplicate ? ' <span class="faint">(already there)</span>' : ""}</td></tr>`).join("")}
      </tbody></table><div class="small faint" style="padding:6px 10px">First ${p.sample.length} rows shown.</div></div>` : ""}
    <div class="toolbar" style="margin-top:12px"><button class="btn btn-primary" id="imp-go">Import now</button></div>`;
  $("#imp-go").onclick = async (e) => {
    e.target.disabled = true;
    try {
      const r = await api.importCommit(formData());
      out.innerHTML = `<div class="callout gain"><b>Imported ${r.imported.toLocaleString("en-IN")} transactions</b>${r.properties ? ` and ${r.properties} items` : ""}.
        ${r.skipped_duplicates ? `${r.skipped_duplicates} were already there. ` : ""}${r.new_items} new items, ${r.new_accounts} new accounts.
        ${r.category_differs.length ? `<br><span class="small">The file's category differs from the stored one for: ${esc(r.category_differs.join(", "))} (stored category kept).</span>` : ""}
        <div style="margin-top:8px"><a class="btn btn-sm" href="#/sheet">Open the sheet</a></div></div>`;
    } catch (err) { out.innerHTML = `<p class="callout loss small">${esc(err.message)}</p>`; }
  };
}
