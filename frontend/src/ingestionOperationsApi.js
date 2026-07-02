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

export function getOperationsSummary() {
  return request("/api/ingestion/operations-summary");
}

export function getDeadLetterEvents(limit = 100) {
  return request(`/api/ingestion/dead-letter?limit=${limit}`);
}

export function requeueEvent(eventId) {
  return request(`/api/ingestion/events/${encodeURIComponent(eventId)}/requeue`, {
    method: "POST",
  });
}

export function requeueAllDeadLetters() {
  return request("/api/ingestion/requeue-all", {
    method: "POST",
  });
}
