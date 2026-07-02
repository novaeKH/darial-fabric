const BASE = `${window.location.protocol}//${window.location.hostname || "localhost"}:8000`;
const KEY = "darial_principal_id";

export function getCurrentPrincipalId() {
  return localStorage.getItem(KEY) || "";
}

export function setCurrentPrincipalId(value) {
  if (value) localStorage.setItem(KEY, value);
  else localStorage.removeItem(KEY);
}

export function principalHeaders(headers = {}) {
  const principalId = getCurrentPrincipalId();
  return {
    ...headers,
    ...(principalId ? { "X-Darial-Principal": principalId } : {}),
  };
}

export async function getSessionPrincipals() {
  const response = await fetch(`${BASE}/api/rbac/principals`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function getPrincipalPermissions(principalId) {
  const response = await fetch(`${BASE}/api/rbac/principals/${encodeURIComponent(principalId)}/permissions`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
