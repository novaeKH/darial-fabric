const DEFAULT_BACKEND = `${window.location.protocol}//${window.location.hostname || "localhost"}:8000`;
const BASE = (import.meta.env.VITE_API_BASE_URL || DEFAULT_BACKEND).replace(/\/$/, "");
const PRINCIPAL_KEY = "darial_principal_id";
const SESSION_KEY = "darial_rbac_session_v2";

function readSession() {
  try {
    const value = JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
    if (!value || typeof value !== "object") return null;
    if (!Array.isArray(value.permissions)) return null;
    return value;
  } catch {
    return null;
  }
}

export function getCurrentPrincipalId() {
  return localStorage.getItem(PRINCIPAL_KEY) || "";
}

export function setCurrentPrincipalId(value) {
  if (value) localStorage.setItem(PRINCIPAL_KEY, value);
  else localStorage.removeItem(PRINCIPAL_KEY);
}

export function principalHeaders(headers = {}) {
  const principalId = getCurrentPrincipalId();
  return {
    ...headers,
    ...(principalId ? { "X-Darial-Principal": principalId } : {}),
  };
}

async function parseResponse(response) {
  if (response.ok) return response.json();
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.json();
    detail = body?.detail || detail;
  } catch {
    // Keep status fallback.
  }
  throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
}

export async function getSessionPrincipals() {
  const response = await fetch(`${BASE}/api/rbac/principals`, {
    headers: { Accept: "application/json" },
  });
  return parseResponse(response);
}

export async function getPrincipalPermissions(principalId) {
  if (!principalId) {
    return { principal: null, permissions: [] };
  }
  const response = await fetch(
    `${BASE}/api/rbac/principals/${encodeURIComponent(principalId)}/permissions`,
    { headers: { Accept: "application/json" } }
  );
  return parseResponse(response);
}

export function getCachedPermissions() {
  const principalId = getCurrentPrincipalId();
  const session = readSession();

  // Never reuse permissions belonging to another principal.
  if (!principalId || !session || session.principalId !== principalId) {
    return [];
  }
  return session.permissions;
}

export function setCachedPermissions(permissions, principalId = getCurrentPrincipalId()) {
  if (!principalId) {
    localStorage.removeItem(SESSION_KEY);
    return;
  }
  localStorage.setItem(
    SESSION_KEY,
    JSON.stringify({
      principalId,
      permissions: Array.isArray(permissions) ? permissions : [],
      refreshedAt: new Date().toISOString(),
    })
  );
}

export function clearRbacSession() {
  localStorage.removeItem(PRINCIPAL_KEY);
  localStorage.removeItem(SESSION_KEY);
  // Remove the old unsafe cache used by earlier builds.
  localStorage.removeItem("darial_permissions");
}

export async function refreshCurrentSession() {
  const principalId = getCurrentPrincipalId();
  if (!principalId) {
    setCachedPermissions([], "");
    return { principal: null, permissions: [] };
  }

  const result = await getPrincipalPermissions(principalId);
  const principal = result?.principal;

  if (!principal || principal.status !== "active") {
    clearRbacSession();
    return { principal: null, permissions: [] };
  }

  const permissions = Array.isArray(result.permissions)
    ? result.permissions
    : [];
  setCachedPermissions(permissions, principalId);
  return { principal, permissions };
}

export async function principalFetch(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: principalHeaders(options.headers || {}),
  });

  if (response.status === 401 || response.status === 403) {
    const error = new Error(
      response.status === 401
        ? "Выберите пользователя Darial"
        : "У выбранной роли нет доступа"
    );
    error.status = response.status;
    try {
      error.payload = await response.json();
    } catch {
      error.payload = null;
    }
    throw error;
  }

  return response;
}
