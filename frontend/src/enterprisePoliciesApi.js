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
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

export function importPolicies(file) {
  const body = new FormData();
  body.append("file", file);
  return request("/api/observability/policies/import", {
    method: "POST",
    body,
  });
}

export async function exportPolicies(format = "yaml") {
  const response = await fetch(
    `${DEFAULT_BACKEND}/api/observability/policies/export?format=${format}`
  );
  if (!response.ok) throw new Error(await response.text());
  return response.blob();
}

export function createCustomPolicy(payload) {
  return request("/api/observability/policies/custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getPolicyVersions(policyId) {
  return request(`/api/observability/policies/${encodeURIComponent(policyId)}/versions`);
}

export function getPolicyAudit() {
  return request("/api/observability/policies/audit");
}
