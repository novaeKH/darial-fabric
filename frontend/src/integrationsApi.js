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

export function getIngestionSummary() {
  return request("/api/ingestion/summary");
}

export function getIngestionSources() {
  return request("/api/ingestion/sources");
}

export function getIngestionEvents(limit = 100) {
  return request(`/api/ingestion/events?limit=${limit}`);
}

export function createIngestionSource(payload) {
  return request("/api/ingestion/sources", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createIngestionKey(sourceId, payload = { name: "default" }) {
  return request(`/api/ingestion/sources/${encodeURIComponent(sourceId)}/keys`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
