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

export function getPolicies() {
  return request("/api/observability/policies");
}

export function createPolicy(payload) {
  return request("/api/observability/policies", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updatePolicy(policyId, payload) {
  return request(`/api/observability/policies/${encodeURIComponent(policyId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function evaluatePolicies() {
  return request("/api/observability/policies/evaluate", {
    method: "POST",
  });
}
