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

export function getViolations(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  return request(`/api/observability/violations?${query.toString()}`);
}

export function getViolationSummary() {
  return request("/api/observability/violations/summary");
}

export function updateViolationStatus(violationId, status) {
  return request(`/api/observability/violations/${encodeURIComponent(violationId)}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}
