// Settings → Users, Roles, Activity and App settings (Admin screens).
import { api } from "../api.js";
import { $, $$, confirmDialog, esc, modal, toast } from "../util.js";

const reloadTab = () => window.dispatchEvent(new HashChangeEvent("hashchange"));

function tempPassword(title, name, pw) {
  return modal({
    title, submitLabel: "Done",
    body: `<p class="small muted" style="margin:0">Give <b>${esc(name)}</b> this temporary password. It is shown only once; they must choose their own at the first login.</p>
      <div class="callout"><code style="font-size:16px;user-select:all">${esc(pw)}</code></div>`,
    onSubmit: () => true,
  });
}

// ---------------------------------------------------------------- users

export async function renderUsers(body) {
  const [users, rs] = await Promise.all([api.users(), api.roles()]);
  const roleOpts = (sel) => rs.roles.map((r) => `<option value="${r.id}" ${r.id === sel ? "selected" : ""}>${esc(r.name)}</option>`).join("");
  body.innerHTML = `<section class="panel"><div class="panel-head"><h2>Users</h2><button class="btn btn-primary btn-sm" id="u-add">Add user</button></div>
    <div class="table-wrap"><table class="master-table"><thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Status</th><th>Authenticator</th><th>Last login</th><th></th></tr></thead><tbody>
    ${users.map((u) => `<tr data-id="${u.id}" class="${u.active ? "" : "inactive"}">
      <td><b>${esc(u.username)}</b></td><td>${esc(u.full_name)}</td>
      <td><select data-f="role_id">${roleOpts(u.role_id)}</select></td>
      <td>${u.active ? `<span class="status-pill on">Active</span>` : `<span class="status-pill off">Disabled</span>`}${u.must_change_password ? ` <span class="small faint">· must change password</span>` : ""}</td>
      <td class="small">${u.mfa_enabled ? "Set up" : "Not yet"}</td>
      <td class="small muted">${esc(u.last_login_at || "never")}</td>
      <td style="white-space:nowrap" class="right">
        <button class="btn btn-sm" data-act="toggle">${u.active ? "Disable" : "Enable"}</button>
        <button class="btn btn-sm" data-act="pw">Reset password</button>
        <button class="btn btn-sm" data-act="mfa">Reset authenticator</button>
        <button class="btn btn-sm" data-act="unlock">Unlock</button>
        <button class="btn btn-sm btn-ghost btn-danger" data-act="del" title="Delete">✕</button></td></tr>`).join("")}</tbody></table></div></section>
    <p class="small faint" style="margin-top:10px">Role changes apply at the user's next request. The roles and what each may do are under <a href="#/settings?s=roles">Roles</a>.</p>`;
  const find = (el) => users.find((u) => u.id === +el.closest("tr").dataset.id);
  $$("select[data-f=role_id]", body).forEach((s) => s.addEventListener("change", async () => {
    const u = find(s);
    try { await api.userSave(u.id, { role_id: +s.value, full_name: u.full_name, active: u.active }); toast("Role changed"); } catch (e) { toast(e.message, true); reloadTab(); }
  }));
  body.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const u = find(b);
    try {
      if (b.dataset.act === "toggle") { await api.userSave(u.id, { role_id: u.role_id, full_name: u.full_name, active: !u.active }); toast(u.active ? "Disabled" : "Enabled"); reloadTab(); }
      else if (b.dataset.act === "pw") {
        if (!(await confirmDialog(`Reset password for ${u.username}?`, "A new temporary password is made; their current logins are signed out.", "Reset"))) return;
        const r = await api.userResetPw(u.id); await tempPassword("New temporary password", u.username, r.temporary_password); reloadTab();
      } else if (b.dataset.act === "mfa") {
        if (!(await confirmDialog(`Reset authenticator for ${u.username}?`, "They scan a new QR code at their next login.", "Reset"))) return;
        await api.userResetMfa(u.id); toast("Authenticator reset"); reloadTab();
      } else if (b.dataset.act === "unlock") { await api.userUnlock(u.id); toast("Unlocked"); }
      else if (b.dataset.act === "del") {
        if (!(await confirmDialog(`Delete ${u.username}?`, "Their entries stay; only the login is removed. Consider Disable instead."))) return;
        await api.userDelete(u.id); toast("Deleted"); reloadTab();
      }
    } catch (err) { toast(err.message, true); }
  });
  $("#u-add").addEventListener("click", async () => {
    let created = null;
    await modal({
      title: "Add user", submitLabel: "Create user",
      body: `<div class="field"><label class="req">Username</label><input name="username" maxlength="40" autocomplete="off"></div>
        <div class="field"><label>Full name</label><input name="full_name" maxlength="80" autocomplete="off"></div>
        <div class="field"><label class="req">Role</label><select name="role_id">${roleOpts(rs.roles.find((r) => r.name === "Editor")?.id)}</select></div>
        <div class="field"><label>Temporary password</label><input name="password" autocomplete="off" placeholder="Leave empty to generate one"></div>`,
      onSubmit: async (v) => { created = await api.userAdd({ ...v, role_id: +v.role_id }); return true; },
    });
    if (created) { await tempPassword("User created", created.username, created.temporary_password); reloadTab(); }
  });
}

// ---------------------------------------------------------------- roles

export async function renderRoles(body) {
  const { roles, catalogue } = await api.roles();
  const keys = Object.keys(catalogue);
  body.innerHTML = `<div class="small muted" style="margin-bottom:12px">A role is a list of things a user may do. The server checks it on every request, so hiding a button is never the only protection.</div>
    <section class="panel"><div class="table-wrap"><table class="master-table role-table"><thead><tr><th>Role</th>${keys.map((k) => `<th title="${esc(catalogue[k])}" class="small">${esc(k)}</th>`).join("")}<th>Users</th><th></th></tr></thead><tbody>
    ${roles.map((r) => `<tr data-id="${r.id}"><td><b>${esc(r.name)}</b>${r.is_system ? ` <span class="faint small">built-in</span>` : ""}<div class="cell-sub">${esc(r.description)}</div></td>
      ${keys.map((k) => `<td class="center"><input type="checkbox" data-p="${k}" ${r.permissions.includes(k) ? "checked" : ""} ${r.name === "Admin" ? "disabled" : ""}></td>`).join("")}
      <td class="num">${r.users}</td>
      <td style="white-space:nowrap">${r.name === "Admin" ? "" : `<button class="btn btn-sm" data-act="save">Save</button>`}${r.is_system ? "" : `<button class="btn btn-sm btn-ghost btn-danger" data-act="del">✕</button>`}</td></tr>`).join("")}
    </tbody></table></div></section>
    <section class="panel panel-pad" style="margin-top:16px;max-width:560px"><h2>What each permission allows</h2>
      <dl class="kv">${keys.map((k) => `<dt><code>${esc(k)}</code></dt><dd>${esc(catalogue[k])}</dd>`).join("")}</dl></section>
    <section class="panel panel-pad" style="margin-top:16px;max-width:560px"><h2>Add a role</h2>
      <form id="r-add" class="stack" novalidate style="margin-top:10px"><div class="field"><label class="req">Name</label><input name="name" maxlength="40"></div>
      <div class="field"><label>Description</label><input name="description" maxlength="120"></div>
      <div class="small" style="display:flex;flex-wrap:wrap;gap:6px 16px">${keys.map((k) => `<label><input type="checkbox" name="p" value="${k}" ${k === "view" ? "checked" : ""}> ${esc(k)}</label>`).join("")}</div>
      <div><button class="btn btn-primary">Add role</button></div></form></section>`;
  body.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const tr = b.closest("tr"), id = +tr.dataset.id;
    try {
      if (b.dataset.act === "save") {
        await api.roleSave(id, { permissions: $$("[data-p]", tr).filter((c) => c.checked).map((c) => c.dataset.p) });
        toast("Role saved"); reloadTab();
      } else if (await confirmDialog("Delete this role?", "Only roles without users can be deleted.")) { await api.roleDelete(id); toast("Deleted"); reloadTab(); }
    } catch (err) { toast(err.message, true); }
  });
  $("#r-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try { await api.roleAdd({ name: fd.get("name"), description: fd.get("description"), permissions: fd.getAll("p") }); toast("Role added"); reloadTab(); }
    catch (err) { toast(err.message, true); }
  });
}

// ---------------------------------------------------------------- activity

export async function renderAudit(body) {
  const rows = await api.audit();
  body.innerHTML = `<section class="panel"><div class="panel-head"><h2>Activity</h2><span class="small faint">newest 200</span></div>
    <div class="table-wrap"><table><thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td class="small">${esc(r.at)}</td><td>${esc(r.actor)}</td><td>${esc(r.action)}</td><td class="small muted">${esc(r.detail)}</td></tr>`).join("") || `<tr><td colspan="4" class="small faint">Nothing yet</td></tr>`}
    </tbody></table></div></section>`;
}

// ---------------------------------------------------------------- app settings

export async function renderAppSettings(body) {
  const o = await api.appSettings();
  const groups = [
    ["Session and login", ["idle_minutes", "session_hours", "max_failures", "lock_minutes", "min_password", "mfa_required"]],
    ["Sheet and display", ["autosave_rows", "currency_symbol"]],
    ["Backups", ["auto_backup_days", "backup_keep"]],
  ];
  const input = (k) => {
    const s = o[k];
    if (s.kind === "bool") return `<label><input type="checkbox" name="${k}" ${s.value ? "checked" : ""}> On</label>`;
    return `<input name="${k}" ${s.kind === "int" ? `type="number" min="${s.min}" max="${s.max}"` : `type="text" maxlength="4"`} value="${esc(s.value)}" style="max-width:140px">`;
  };
  body.innerHTML = `<form id="as" class="stack" novalidate style="max-width:720px">${groups.map(([title, keys]) => `
    <section class="panel panel-pad"><h2>${title}</h2>${keys.map((k) => `<div class="field" data-field="${k}" style="margin-top:12px"><label>${esc(o[k].label)}</label>
      ${input(k)}<div class="hint small faint">${esc(o[k].help)} Default: ${o[k].kind === "bool" ? (o[k].default ? "on" : "off") : esc(o[k].default)}.</div><div class="err hidden"></div></div>`).join("")}</section>`).join("")}
    <div><button class="btn btn-primary">Save settings</button></div></form>`;
  $("#as").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target), payload = {};
    Object.keys(o).forEach((k) => { payload[k] = o[k].kind === "bool" ? fd.has(k) : fd.get(k); });
    $$(".field", e.target).forEach((f) => { f.classList.remove("has-error"); $(".err", f).classList.add("hidden"); });
    try { await api.saveAppSettings(payload); toast("Settings saved. They apply right away."); }
    catch (err) {
      const f = err.field && $(`[data-field="${err.field}"]`, e.target);
      if (f) { f.classList.add("has-error"); const m = $(".err", f); m.textContent = err.message; m.classList.remove("hidden"); } else toast(err.message, true);
    }
  });
}
