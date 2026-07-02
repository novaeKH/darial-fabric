import { principalHeaders } from "./sessionApi";
const DEFAULT_BACKEND = `${window.location.protocol}//${window.location.hostname || "localhost"}:8000`;

async function request(path, options = {}) {
  const response = await fetch(`${DEFAULT_BACKEND}${path}`, {
    ...options,
    headers: principalHeaders({
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  return response.json();
}

export function getRbacSummary() {
  return request("/api/rbac/summary");
}

export function getPrincipals() {
  return request("/api/rbac/principals");
}

export function getRoles() {
  return request("/api/rbac/roles");
}

export function getRbacAudit() {
  return request("/api/rbac/audit");
}

export function createPrincipal(payload) {
  return request("/api/rbac/principals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createAssignment(payload) {
  return request("/api/rbac/assignments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteAssignment(assignmentId) {
  return request(`/api/rbac/assignments/${encodeURIComponent(assignmentId)}`, {
    method: "DELETE",
  });
}

export function updatePrincipalStatus(principalId, status) {
  return request(`/api/rbac/principals/${encodeURIComponent(principalId)}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}
