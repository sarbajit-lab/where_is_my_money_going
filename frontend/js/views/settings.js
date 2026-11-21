// Settings: your account, app settings, users & roles (Admin), backups and the classic lists.
import { api } from "../api.js";
import { invalidateMasters, masters } from "../state.js";
import { $, $$, confirmDialog, dateLabel, esc, modal, toast } from "../util.js";
import { can } from "../state.js";
import * as adminViews from "./users.js";

const SECTIONS = {
  account: ["My account", () => true],
  app: ["App settings", () => can("settings.manage")],
  users: ["Users", () => can("users.manage")],
  roles: ["Roles", () => can("users.manage")],
  activity: ["Activity", () => can("users.manage")],
  data: ["Backup & export", () => can("backup.manage")],
  categories: ["Classic: categories", () => can("masters.write")],
  payment_modes: ["Classic: payment modes", () => can("masters.write")],
  about: ["About & changelog", () => true],
};

export async function render(params) {
  if (params.s === "accounts") { location.hash = "#/accounts"; return; }
  if (params.s === "security") params = { ...params, s: "account" };
  const allowed = Object.keys(SECTIONS).filter((k) => SECTIONS[k][1]());
  const sec = allowed.includes(params.s) ? params.s : "account";
  $("#view").innerHTML = `
    <div class="page-head"><div><h1>Settings</h1><div class="sub small muted">${can("settings.manage") ? "Security rules, users and roles, backups." : "Your account."}</div></div></div>
    <div class="tabs">${allowed.map((k) => `<button data-s="${k}" class="${k === sec ? "on" : ""}">${SECTIONS[k][0]}</button>`).join("")}</div>
    <div id="set-body"></div>`;
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => { location.hash = `#/settings?s=${b.dataset.s}`; }));
  const body = $("#set-body");
  if (sec === "account") await security(body);
  if (sec === "app") await adminViews.renderAppSettings(body);
  if (sec === "users") await adminViews.renderUsers(body);
  if (sec === "roles") await adminViews.renderRoles(body);
  if (sec === "activity") await adminViews.renderAudit(body);
  if (sec === "data") await data(body);
  if (sec === "about") await about(body);
  if (sec === "categories" || sec === "payment_modes") {
    const M = await masters(true);
    if (sec === "categories") categories(body, M.categories); else simple(body, "payment_modes", M.payment_modes, "Payment mode");
  }
}

const reload = () => { invalidateMasters(); render(Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || ""))); };

async function saveRow(table, id, payload) {
  try {
    await api.updateMaster(table, id, payload);
    toast("Saved");
    reload();
  } catch (e) { toast(e.message, true); }
}

async function deleteRow(table, item) {
  const ok = await confirmDialog(`Delete “${item.name}”?`, "This can't be undone.");
  if (!ok) return;
  try {
    await api.deleteMaster(table, item.id);
    toast("Deleted");
    reload();
  } catch (e) { toast(e.message, true); }
}

async function addRow(table, payload) {
  try {
    const created = await api.createMaster(table, payload);
    toast(`Added ${created.name}`);
    reload();
  } catch (e) { toast(e.message, true); }
}

function rowActions(item) {
  return `<td style="white-space:nowrap" class="right">
    <button class="btn btn-sm" data-save="${item.id}">Save</button>
    ${item.used ? "" : `<button class="btn btn-sm btn-ghost btn-danger" data-del="${item.id}" title="Delete">✕</button>`}
  </td>`;
}

function categories(body, list) {
  const block = (kind) => {
    const items = list.filter((c) => c.kind === kind);
    return `<section class="panel" style="margin-bottom:16px">
      <div class="panel-head" style="padding-bottom:12px"><h2>${kind === "expense" ? "Expense" : "Income"} categories</h2><span class="small faint">${items.length}</span></div>
      <div class="table-wrap"><table class="master-table">
        <thead><tr><th>Name</th><th class="hide-sm">Description</th><th>Active</th><th class="num">Transactions</th><th></th></tr></thead>
        <tbody>${items.map((c) => c.is_system ? `
          <tr><td><b>${esc(c.name)}</b></td><td class="hide-sm small muted">${esc(c.description || "")}</td><td>✓</td><td class="num muted">${c.used}</td><td class="small faint right">automatic</td></tr>` : `
          <tr data-id="${c.id}" class="${c.active ? "" : "inactive"}">
            <td><input type="text" name="name" value="${esc(c.name)}" maxlength="80"></td>
            <td class="hide-sm"><input type="text" name="description" value="${esc(c.description || "")}" placeholder="What goes here"></td>
            <td><input type="checkbox" name="active" ${c.active ? "checked" : ""}></td>
            <td class="num muted">${c.used}</td>
            ${rowActions(c)}
          </tr>`).join("")}</tbody>
      </table></div>
      <form class="add-row" data-kind="${kind}">
        <input type="text" name="name" placeholder="New ${kind} category" required maxlength="80">
        <input type="text" name="description" placeholder="Description" class="hide-sm">
        <button class="btn btn-primary">Add</button>
      </form>
    </section>`;
  };
  body.innerHTML = block("expense") + block("income");
  bindTable(body, "categories", list, (tr) => ({
    name: $("[name=name]", tr).value, description: $("[name=description]", tr).value, active: $("[name=active]", tr).checked,
  }));
  $$("form[data-kind]", body).forEach((f) => f.addEventListener("submit", (e) => {
    e.preventDefault();
    addRow("categories", { ...Object.fromEntries(new FormData(f).entries()), kind: f.dataset.kind });
  }));
}

function simple(body, table, list, label) {
  body.innerHTML = `
    <section class="panel" style="max-width:640px">
      <div class="table-wrap"><table class="master-table">
        <thead><tr><th>Name</th><th>Active</th><th class="num">Transactions</th><th></th></tr></thead>
        <tbody>${list.map((m) => `
          <tr data-id="${m.id}" class="${m.active ? "" : "inactive"}">
            <td><input type="text" name="name" value="${esc(m.name)}" maxlength="80"></td>
            <td><input type="checkbox" name="active" ${m.active ? "checked" : ""}></td>
            <td class="num muted">${m.used}</td>
            ${rowActions(m)}
          </tr>`).join("")}</tbody>
      </table></div>
      <form class="add-row" id="add-form">
        <input type="text" name="name" placeholder="New ${label.toLowerCase()}" required maxlength="80">
        <button class="btn btn-primary">Add</button>
      </form>
    </section>`;
  bindTable(body, table, list, (tr) => ({ name: $("[name=name]", tr).value, active: $("[name=active]", tr).checked }));
  $("#add-form").addEventListener("submit", (e) => { e.preventDefault(); addRow(table, Object.fromEntries(new FormData(e.target).entries())); });
}

function bindTable(body, table, list, read) {
  $$("[data-save]", body).forEach((b) => b.addEventListener("click", () => {
    const tr = b.closest("tr");
    saveRow(table, +b.dataset.save, read(tr));
  }));
  $$("[data-del]", body).forEach((b) => b.addEventListener("click", () => {
    deleteRow(table, list.find((x) => x.id === +b.dataset.del));
  }));
  // Enter in a row's input saves that row
  $$("tbody input[type=text], tbody input[type=number]", body).forEach((inp) => inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("[data-save]", inp.closest("tr"))?.click(); }
  }));
}

async function data(body) {
  const [info, backups] = await Promise.all([api.info(), api.backups()]);
  const range = info.entries ? `${esc(dateLabel(info.first_entry))} – ${esc(dateLabel(info.last_entry))}` : "No transactions yet";
  body.innerHTML = `
    <div class="grid grid-2">
      <div class="stack">
        <section class="panel panel-pad">
          <h2>Your database</h2>
          <table style="margin-top:10px"><tbody>
            <tr><td class="muted">Sheet entries recorded</td><td class="num">${info.entries.toLocaleString("en-IN")}</td></tr>
            <tr><td class="muted">Dates covered</td><td class="num">${range}</td></tr>
            <tr><td class="muted">Stored at</td><td class="small" style="word-break:break-all">${esc(info.db_path)}</td></tr>
            <tr><td class="muted">Version</td><td class="small">App ${esc(info.app_version)} · database ${info.schema_version}</td></tr>
          </tbody></table>
          <div class="form-actions"><a class="btn" href="#/transfer">Import &amp; export the sheet</a></div>
        </section>

        <section class="panel panel-pad">
          <h2>Back up to a folder</h2>
          <p class="small muted" style="margin:6px 0 12px">Saves a copy of your database there, named with today's date and time.
            A pen drive or another disk keeps a copy safe even if this computer fails.</p>
          <form id="bk-form" class="stack" style="gap:10px" novalidate>
            <div class="field" data-field="path"><label class="req">Folder (full path)</label>
              <input name="path" id="bk-path" value="${esc(info.backup_folder || "")}" placeholder="e.g. /media/you/PENDRIVE/Backups" autocomplete="off" spellcheck="false">
              <div class="err hidden"></div></div>
            <div><button class="btn btn-primary">Back up now</button></div>
          </form>
        </section>

        <section class="panel panel-pad">
          <h2>Restore from a file</h2>
          <p class="small muted" style="margin:6px 0 12px">Replaces <b>all</b> your current data with the backup file you choose.
            Your current data is saved to the backups list first, so you can undo it.</p>
          <form id="rs-form" class="stack" style="gap:10px" novalidate>
            <div class="field" data-field="file"><label class="req">Backup file (.db)</label>
              <input type="file" name="file" accept=".db,application/x-sqlite3,application/vnd.sqlite3"><div class="err hidden"></div></div>
            <div class="field" data-field="password"><label class="req">Your password</label>
              <input type="password" name="password" autocomplete="current-password"><div class="err hidden"></div></div>
            <div><button class="btn btn-danger">Restore</button></div>
          </form>
        </section>
      </div>

      <section class="panel panel-pad">
        <h2>Automatic backups <span class="faint small">· newest 10</span></h2>
        <p class="small muted" style="margin:6px 0 0">Made once a week (on the first start after 7 days), before any database upgrade, and before a restore.
          Only the newest backups are kept (you choose how many in App settings); older ones are deleted automatically. They're in <code>${esc(info.backup_dir)}</code>.</p>
        <div class="table-wrap" style="margin-top:14px;max-height:520px;overflow:auto">
          <table><thead><tr><th>Backup</th><th class="num">Size</th><th></th></tr></thead>
          <tbody>${backups.map((b) => `<tr><td><div class="small">${esc(b.created)}</div><div class="cell-sub">${esc(kindOf(b.file))}</div></td>
            <td class="num small muted">${b.size_kb} KB</td>
            <td class="right"><button class="btn btn-sm" data-restore="${esc(b.file)}">Restore</button></td></tr>`).join("")
            || `<tr><td colspan="3" class="small faint">No backups yet</td></tr>`}</tbody></table>
        </div>
      </section>
    </div>`;

  const clearErr = (form) => $$(".field", form).forEach((f) => { f.classList.remove("has-error"); $(".err", f)?.classList.add("hidden"); });
  const showErr = (form, e) => {
    clearErr(form);
    const f = e.field && $(`[data-field="${e.field}"]`, form);
    if (f) { f.classList.add("has-error"); const el = $(".err", f); el.textContent = e.message; el.classList.remove("hidden"); }
    else toast(e.message, true);
  };

  $("#bk-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = $("button", ev.target); btn.disabled = true;
    try {
      const r = await api.backupTo($("#bk-path").value);
      clearErr(ev.target);
      toast(`Backed up to ${r.file}`);
    } catch (e) { showErr(ev.target, e); }
    btn.disabled = false;
  });

  const afterRestore = (r) => {
    toast(`Restored. Your previous data was saved as ${r.saved_current_as}. Please log in again.`);
    setTimeout(() => { location.hash = "#/dashboard"; location.reload(); }, 1800);
  };

  $("#rs-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target, fd = new FormData(form);
    if (!form.file.files.length) return showErr(form, { field: "file", message: "Choose the backup file" });
    if (!fd.get("password")) return showErr(form, { field: "password", message: "Enter your password" });
    if (!(await confirmDialog("Restore this backup?", `All current data will be replaced with ${form.file.files[0].name}. Your current data is saved first.`, "Restore"))) return;
    const btn = $("button", form); btn.disabled = true;
    try { afterRestore(await api.restoreUpload(fd)); } catch (e) { showErr(form, e); btn.disabled = false; }
  });

  $$("[data-restore]").forEach((b) => b.addEventListener("click", async () => {
    const name = b.dataset.restore;
    const pw = await modal({
      title: "Restore this backup?",
      body: `<p class="small muted" style="margin:0">All current data will be replaced with the backup from <b>${esc(backups.find((x) => x.file === name)?.created || name)}</b>.
        Your current data is saved first, so you can undo this.</p>
        <div class="field"><label class="req">Your password</label><input type="password" name="password" autocomplete="current-password"></div>`,
      submitLabel: "Restore",
      onSubmit: async (v) => {
        if (!v.password) throw new Error("Enter your password");
        return api.restoreBackup(name, v.password);
      },
    });
    if (pw) afterRestore(pw);
  }));
}

function kindOf(file) {
  if (file.includes("_pre-restore")) return "Before a restore";
  if (file.includes("_pre-migration")) return "Before an app update";
  if (file.includes("_manual")) return "Made by you";
  if (file.includes("_auto")) return "Weekly automatic";
  return file;
}

// ---------------------------------------------------------------- my account

function secField(name, label, value = "", type = "text", extra = "") {
  return `<div class="field" data-field="${name}"><label>${label}</label>
    <input name="${name}" type="${type}" value="${esc(value)}" ${extra}><div class="err hidden"></div></div>`;
}

function bindForm(form, handler) {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    form.querySelectorAll(".field").forEach((f) => { f.classList.remove("has-error"); $(".err", f)?.classList.add("hidden"); });
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    try {
      await handler(Object.fromEntries(new FormData(form).entries()));
    } catch (err) {
      const f = err.field && form.querySelector(`[data-field="${err.field}"]`);
      if (f) { f.classList.add("has-error"); const el = $(".err", f); el.textContent = err.message; el.classList.remove("hidden"); }
      else toast(err.message, true);
    } finally { btn.disabled = false; }
  });
}

async function security(body) {
  const s = await api.security();
  const u = s.user;
  body.innerHTML = `
    <div class="sec-grid">
      <section class="panel panel-pad">
        <h2>Profile</h2>
        <p class="small muted" style="margin:0">Logged in as <b>${esc(u.username)}</b> · role <b>${esc(u.role)}</b>${u.last_login_at ? ` · last login ${esc(u.last_login_at)}` : ""}</p>
        <form id="pf-form" novalidate>${secField("full_name", "Your name", u.full_name, "text", 'maxlength="80"')}<div><button type="submit" class="btn">Save name</button></div></form>
        <p class="small muted" style="margin:14px 0 4px"><b>You can:</b> ${u.permissions.map((p) => `<code>${esc(p)}</code>`).join(" ")}</p>
      </section>
      <section class="panel panel-pad">
        <h2>Password</h2>
        <form id="pw-form" novalidate>
          ${secField("current", "Current password", "", "password", 'autocomplete="current-password"')}
          ${secField("new", "New password", "", "password", 'autocomplete="new-password"')}
          ${secField("confirm", "Repeat new password", "", "password", 'autocomplete="new-password"')}
          <div class="hint small faint">At least ${s.min_password} characters. Your other open logins are signed out.</div>
          <div><button type="submit" class="btn btn-primary">Change password</button></div>
        </form>
      </section>
      <section class="panel panel-pad">
        <h2>Authenticator app (MFA) <span class="status-pill ${u.mfa_enabled ? "on" : "off"}">${u.mfa_enabled ? "On" : "Off"}</span></h2>
        <p class="small muted">${s.mfa_required ? "Every login needs a 6-digit code from your phone." : "An Admin has made the code optional."} Got a new phone? Pair it here; the old one stops working.</p>
        <a class="btn" href="#/new-authenticator">Set up on a new phone</a>
        <p class="small faint" style="margin:14px 0 0">Lost your phone? Ask an Admin to reset it, or run <code>python3 run.py --reset-mfa --user ${esc(u.username)}</code> on this computer.</p>
        <p class="small faint" style="margin:10px 0 0">You are logged out after ${s.idle_minutes} idle minutes (set by an Admin).</p>
      </section>
      <section class="panel panel-pad">
        <div class="callout small"><strong>Good to know:</strong> the login protects the app. Your data file (<code>data/wimmg.db</code>)
          is a normal file on this computer, so also keep your computer account password-protected. No data is ever sent over the internet.</div>
      </section>
    </div>`;
  bindForm($("#pw-form"), async (d) => { await api.changePassword(d); toast("Password changed"); $("#pw-form").reset(); });
  bindForm($("#pf-form"), async (d) => { await api.saveProfile(d); toast("Saved"); });
}

// ---------------------------------------------------------------- about

function md(text) {
  const lines = esc(text).split("\n");
  let html = "", list = false;
  for (const ln of lines) {
    const li = ln.match(/^\s*[-*] (.*)/);
    if (li) { if (!list) { html += "<ul>"; list = true; } html += `<li>${li[1].replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>")}</li>`; continue; }
    if (list) { html += "</ul>"; list = false; }
    const h = ln.match(/^(#{1,3}) (.*)/);
    if (h) html += `<h${h[1].length + 1} style="margin:14px 0 6px">${h[2]}</h${h[1].length + 1}>`;
    else if (ln.trim()) html += `<p style="margin:6px 0">${ln.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>")}</p>`;
  }
  return html + (list ? "</ul>" : "");
}

async function about(body) {
  const [info, log] = await Promise.all([api.info(), api.changelog()]);
  body.innerHTML = `<div class="grid grid-2">
    <section class="panel panel-pad"><div style="display:flex;gap:14px;align-items:center"><img src="/img/logo.svg" width="64" height="64" alt="WIMMG logo">
      <div><h2 style="font-size:20px">WIMMG</h2><div class="muted small">Where Is My Money Going? · version ${esc(info.app_version)}</div></div></div>
      <p class="small" style="margin:14px 0 4px">Made by <b>House of Lad Pal (HLP)</b>. Created by <b>Sarbajit Pal</b>.</p>
      <p class="small muted" style="margin:0">MIT licence. A private, offline personal money ledger: it never connects to the internet.</p>
      <table style="margin-top:12px"><tbody>
        <tr><td class="muted">Entries</td><td class="num">${info.entries.toLocaleString("en-IN")}</td></tr>
        <tr><td class="muted">Items</td><td class="num">${info.items.toLocaleString("en-IN")}</td></tr>
        <tr><td class="muted">Database</td><td class="small" style="word-break:break-all">${esc(info.db_path)} (schema ${info.schema_version})</td></tr></tbody></table></section>
    <section class="panel panel-pad"><h2>What's new in this version</h2><div class="small">${md(log.release_notes || "No release notes found.")}</div></section></div>
    <section class="panel panel-pad" style="margin-top:16px"><h2>Changelog</h2><div class="small">${md(log.changelog || "No changelog found.")}</div></section>`;
}
