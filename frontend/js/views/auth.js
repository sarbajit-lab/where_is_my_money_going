// Login (username + password + authenticator code), first-time password change, authenticator setup.
import { api } from "../api.js";
import { qrSvg } from "../vendor/qrcode.js";
import { $, esc } from "../util.js";

const view = () => $("#view");

function shell(title, sub, body) {
  view().innerHTML = `
    <div class="auth-wrap">
      <div class="auth-brand">
        <img class="brand-logo" src="/img/logo.svg" alt="WIMMG logo" width="56" height="56">
        <span class="brand-name">WIMMG<small>Where Is My Money Going?</small></span>
      </div>
      <div class="panel auth-card">
        <h1>${title}</h1>
        ${sub ? `<p class="muted small auth-sub">${sub}</p>` : ""}
        ${body}
      </div>
      <p class="faint small auth-foot">Runs only on this computer · works offline · your data never leaves it<br>WIMMG by Sarbajit Pal · House of Lad Pal (HLP)</p>
    </div>`;
}

function field(name, label, type = "text", extra = "") {
  return `<div class="field" data-field="${name}">
    <label for="a-${name}">${label}</label>
    <input id="a-${name}" name="${name}" type="${type}" ${extra}>
    <div class="err hidden"></div></div>`;
}

function codeField() {
  return field("code", "6-digit code", "text",
    'inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]*" maxlength="7" class="code-input" placeholder="000 000" required');
}

function showErr(form, err) {
  form.querySelectorAll(".field").forEach((f) => { f.classList.remove("has-error"); $(".err", f)?.classList.add("hidden"); });
  const f = err.field && form.querySelector(`[data-field="${err.field}"]`);
  if (f) {
    f.classList.add("has-error");
    const e = $(".err", f);
    e.textContent = err.message;
    e.classList.remove("hidden");
    $("input", f).focus();
  } else {
    const box = $(".form-err", form);
    box.textContent = err.message;
    box.classList.remove("hidden");
  }
}

function onSubmit(form, handler) {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    $(".form-err", form)?.classList.add("hidden");
    try {
      await handler(Object.fromEntries(new FormData(form).entries()));
    } catch (err) {
      showErr(form, err);
    } finally {
      btn.disabled = false;
    }
  });
}

const errBox = `<p class="form-err callout loss small hidden" role="alert"></p>`;
const pwHint = `<div class="hint">At least 10 characters, with letters and numbers or symbols.</div>`;

// ---------------------------------------------------------------- first login: choose your own password

export function renderFirstPassword(done, { username = "", minPassword = 10 } = {}) {
  shell("Choose your own password", `Hello <b>${esc(username)}</b>. The password you just used is temporary: set one only you know.`, `
    <form id="f" class="stack" novalidate>
      ${field("current", "Temporary password (the one you just used)", "password", 'autocomplete="current-password" required')}
      ${field("new", "New password", "password", 'autocomplete="new-password" required')}
      <div class="hint">At least ${minPassword} characters, with letters and numbers or symbols.</div>
      ${field("confirm", "Repeat new password", "password", 'autocomplete="new-password" required')}
      ${errBox}
      <button type="submit" class="btn btn-primary btn-block">Save and continue</button>
    </form>`);
  $("#a-current").focus();
  onSubmit($("#f"), async (d) => { await api.firstPassword(d); done(); });
}

// ---------------------------------------------------------------- authenticator setup

export async function renderMfaSetup(done, { fromSettings = false } = {}) {
  const { secret, uri } = await api.mfaBegin();
  const pretty = secret.replace(/(.{4})/g, "$1 ").trim();
  const body = `
    <ol class="mfa-steps small">
      <li>Open <b>Google Authenticator</b>, <b>Microsoft Authenticator</b> or <b>Authy</b> on your phone and tap <b>+</b>.</li>
      <li>Scan this QR code.</li>
    </ol>
    <div class="qr-box">${qrSvg(uri, { size: 208 })}</div>
    <details class="small muted manual-key">
      <summary>Can't scan? Enter this key instead</summary>
      <code class="secret">${esc(pretty)}</code>
      <div class="faint">Account: WIMMG · Time based · 6 digits</div>
    </details>
    <form id="f" class="stack" novalidate style="margin-top:14px">
      ${codeField()}
      <div class="hint" style="margin-top:-8px">3. Type the 6-digit code the app now shows for WIMMG.</div>
      ${errBox}
      <button type="submit" class="btn btn-primary btn-block">Turn on and continue</button>
      ${fromSettings ? `<a class="btn btn-ghost btn-block" href="#/settings?s=security">Cancel</a>` : ""}
    </form>`;
  if (fromSettings) {
    view().innerHTML = `<div class="page-head"><div><h1>Set up authenticator on a new phone</h1>
      <div class="sub small muted">Your old phone's code stops working once you confirm.</div></div></div>
      <div class="panel auth-card" style="margin:0">${body}</div>`;
  } else {
    shell("Set up your authenticator", "Every login will ask for a 6-digit code from your phone.", body);
  }
  $("#a-code").focus();
  onSubmit($("#f"), async (d) => { await api.mfaConfirm(d.code); done(); });
}

// ---------------------------------------------------------------- login

export function renderLogin(done, { message } = {}) {
  shell("Log in", "", `
    ${message ? `<p class="callout gain small">${esc(message)}</p>` : ""}
    <form id="f" class="stack" novalidate>
      ${field("username", "Username", "text", 'autocomplete="username" autocapitalize="none" spellcheck="false" required')}
      ${field("password", "Password", "password", 'autocomplete="current-password" required')}
      ${errBox}
      <button type="submit" class="btn btn-primary btn-block">Continue</button>
      <p class="small faint center-link" style="margin:0">First time? Use <b>admin</b> and the password shown in the terminal window.</p>
    </form>`);
  $("#a-username").focus();
  onSubmit($("#f"), async (d) => {
    const s = await api.login(d);
    if (s.state === "mfa") renderCode(done);
    else if (s.state === "change_pw") renderFirstPassword(done, { username: s.username, minPassword: s.min_password });
    else if (s.state === "mfa_setup") { await renderMfaSetup(done); }
    else done();
  });
}

export function renderCode(done) {
  shell("Enter your code", "Open your authenticator app and type the 6-digit code for WIMMG.", `
    <form id="f" class="stack" novalidate>
      ${codeField()}
      ${errBox}
      <button type="submit" class="btn btn-primary btn-block">Log in</button>
      <a class="small center-link" href="#/login" id="back">← Use a different account</a>
    </form>
    <details class="small muted" style="margin-top:14px">
      <summary>Lost your phone?</summary>
      <p>Ask an Admin to reset your authenticator (Settings → Users), or on this computer stop the app and run
      <code>python3 run.py --reset-mfa --user YOURNAME</code> in the app's folder. You'll scan a new QR code.</p>
    </details>`);
  const input = $("#a-code");
  input.focus();
  input.addEventListener("input", () => {
    if (input.value.replace(/\D/g, "").length === 6) $("#f").requestSubmit();
  });
  $("#back").addEventListener("click", async (e) => { e.preventDefault(); await api.logout().catch(() => {}); renderLogin(done); });
  onSubmit($("#f"), async (d) => { await api.loginCode(d.code); done(); });
}
