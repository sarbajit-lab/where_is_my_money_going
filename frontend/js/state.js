// Cached master data (classic accounts, categories, payment modes) and who is logged in.
import { api } from "./api.js";

let cache = null;

export async function masters(force = false) {
  if (!cache || force) cache = await api.masters();
  return cache;
}

export function invalidateMasters() {
  cache = null;
}

export const active = (list) => list.filter((x) => x.active);

// ---- the logged-in user (set by main.js after every status check)
export const session = { user: null, version: "", minPassword: 10, mfaRequired: true, autosave: true };

export function setSession(st) {
  session.user = st.user || null;
  session.version = st.version || session.version;
  session.minPassword = st.min_password || 10;
  session.mfaRequired = st.mfa_required !== false;
  session.autosave = st.autosave_rows !== false;
}

/** Does the current user's role allow this? (The server checks again on every request.) */
export const can = (perm) => !!session.user && session.user.permissions.includes(perm);
