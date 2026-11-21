// Hash router: #/sheet (home), #/limits, #/insights, #/transfer, #/settings and the classic screens (#/dashboard, #/entries, ...).
// Every screen requires a full login (password + authenticator code) and the permission of the user's role.
import { api } from "./api.js";
import { $, $$, esc, goBack, notePageChange, toast } from "./util.js";
import * as auth from "./views/auth.js";
import * as dashboard from "./views/dashboard.js";
import * as entries from "./views/entries.js";
import * as entryForm from "./views/entry-form.js";
import * as investment from "./views/investment.js";
import * as investments from "./views/investments.js";
import * as loans from "./views/loans.js";
import * as moneyView from "./views/money.js";
import * as budget from "./views/budget.js";
import * as reports from "./views/reports.js";
import * as settings from "./views/settings.js";
import * as sheet from "./views/sheet.js";
import * as limits from "./views/limits.js";
import * as insights from "./views/insights.js";
import * as transfer from "./views/transfer.js";
import * as setup from "./views/setup.js";
import { initTheme } from "./theme.js";
import { can, setSession } from "./state.js";
import { setCurrency } from "./util.js";
import { initPicker } from "./picker.js";

const routes = {
  sheet: (p) => sheet.render(p),
  limits: (p) => limits.render(p),
  insights: (p) => insights.render(p),
  transfer: (p) => transfer.render(p),
  dashboard: (p) => dashboard.render(p),
  accounts: (p) => moneyView.render(p),
  money: (p) => moneyView.render(p),        // old address of Accounts
  entries: (p) => entries.render(p),
  add: (p) => entryForm.render({ ...p }),
  edit: (p, id) => entryForm.render({ ...p, id }),
  investments: (p) => investments.render(p),
  investment: (p, id) => investment.render(p, id),
  loans: (p) => loans.render(p),
  loan: (p, id) => loans.renderLoan(p, id),
  budget: (p) => budget.render(p),
  planner: (p) => budget.render(p),        // old address of the Monthly Budget
  reports: (p) => reports.render(p),
  settings: (p) => settings.render(p),
  setup: (p) => setup.render(p),
  "new-authenticator": () => auth.renderMfaSetup(() => { toast("Authenticator updated"); location.hash = "#/settings?s=security"; }, { fromSettings: true }),
};
const AUTH_ROUTES = ["login"];
const HOME = "sheet";

function parse() {
  const raw = location.hash.replace(/^#\/?/, "") || HOME;
  const [path, query = ""] = raw.split("?");
  const [name, arg] = path.split("/");
  const known = routes[name] || AUTH_ROUTES.includes(name);
  return { name: known ? name : HOME, arg, params: Object.fromEntries(new URLSearchParams(query)) };
}

function authMode(on) {
  document.body.classList.toggle("auth-mode", on);
}

// after a successful login step: continue to where the user was going
function proceed(message) {
  const { name } = parse();
  if (AUTH_ROUTES.includes(name)) {
    if (message) { history.replaceState(null, "", "/#/login"); navigate({ message }); return; }
    location.hash = `#/${HOME}`;
  } else {
    navigate();
  }
}

/** Shows the right login step if needed. Returns true when the user is fully logged in. */
async function ensureLoggedIn(name, params, extra = {}) {
  const st = await api.authStatus();
  if (st.state === "ok") { authMode(false); applySession(st); return true; }
  authMode(true);
  if (st.state === "change_pw") auth.renderFirstPassword(proceed, { username: st.username, minPassword: st.min_password });
  else if (st.state === "mfa_setup") await auth.renderMfaSetup(proceed);
  else if (st.state === "mfa") auth.renderCode(proceed);
  else auth.renderLogin(proceed, extra);
  return false;
}

/** Remember who is logged in, show only the menu items their role allows. */
function applySession(st) {
  setSession(st);
  setCurrency(st.currency);
  $("#who").textContent = st.user ? `${st.user.full_name || st.user.username} · ${st.user.role}` : "";
  $$("#nav a").forEach((a) => {
    if (a.dataset.route === "transfer") a.classList.toggle("hidden", !(can("data.import") || can("data.export")));
  });
}

async function navigate(extra = {}) {
  let { name, arg, params } = parse();
  const dialog = $("#modal-root");
  if (dialog) dialog.innerHTML = "";          // a dialog left open never follows you to another page
  try {
    if (!(await ensureLoggedIn(name, params, extra))) return;
  } catch (err) {
    $("#view").innerHTML = `<div class="panel empty"><div class="big">⚠</div><p>${esc(err.message)}</p>
      <button class="btn" data-retry>Retry</button></div>`;
    return;
  }
  if (AUTH_ROUTES.includes(name)) { location.hash = `#/${HOME}`; return; }
  document.body.classList.toggle("on-classic", ["dashboard", "entries", "accounts", "money", "investments", "investment", "loans", "loan", "budget", "planner", "reports", "add", "edit"].includes(name));
  const nav = name === "add" || name === "edit" ? "entries" : name === "investment" ? "investments" : name === "loan" ? "loans" : name === "planner" ? "budget" : name === "money" ? "accounts" : ["setup", "new-authenticator"].includes(name) ? "settings" : name;
  document.body.classList.toggle("on-form", name === "add" || name === "edit");
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === nav));
  const view = $("#view");
  view.innerHTML = `<div class="loading">Loading…</div>`;
  $("#chart-tip").style.display = "none";
  try {
    await routes[name](params, arg);
  } catch (err) {
    console.error(err);
    view.innerHTML = `<div class="panel empty"><div class="big">⚠</div><p>${esc(err.message)}</p>
      <button class="btn" data-retry>Retry</button></div>`;
  }
  window.scrollTo(0, 0);
}

initTheme();

// Dropdowns: a mouse click opens the app's own list (see picker.js), the wheel never changes a focused dropdown.
initPicker();

// The browser must not remember what you type (amounts, notes, stock names...) and offer it again later.
// Fields that say what they are (email, passwords, the login code) keep their own autocomplete setting.
const noHistory = (root) => {
  if (!root.querySelectorAll) return;
  const els = [root, ...root.querySelectorAll("form, input, textarea")];
  for (const el of els) {
    if (!["FORM", "INPUT", "TEXTAREA"].includes(el.tagName) || el.hasAttribute("autocomplete")) continue;
    if (el.tagName === "FORM" && el.querySelector("[autocomplete]:not([autocomplete=off])")) continue;   // login forms
    el.setAttribute("autocomplete", "off");
  }
};
noHistory(document.body);
new MutationObserver((list) => {
  for (const m of list) for (const n of m.addedNodes) if (n.nodeType === 1) noHistory(n);
}).observe(document.body, { childList: true, subtree: true });

window.addEventListener("hashchange", () => { notePageChange(); navigate(); });
document.addEventListener("click", (e) => {        // back buttons and Cancel: return to the page you came from
  const b = e.target.closest("a[data-back]");
  if (!b || e.ctrlKey || e.metaKey || e.shiftKey) return;
  e.preventDefault();
  goBack(b.getAttribute("href"));
});
document.addEventListener("click", (e) => { if (e.target.closest("[data-retry]")) location.reload(); });
window.addEventListener("wimmg:logged-out", () => {
  if (!document.body.classList.contains("auth-mode")) { toast("You were logged out"); navigate(); }
});
$("#logout-btn").addEventListener("click", async () => {
  await api.logout().catch(() => {});
  location.hash = `#/${HOME}`;
  navigate();
});
navigate();
