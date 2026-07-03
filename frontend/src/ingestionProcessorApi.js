import { principalHeaders } from "./sessionApi";

const BASE =
  `${window.location.protocol}//${window.location.hostname || "localhost"}:8000`;

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: principalHeaders({
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    }),
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

export const getProcessingSummary = () =>
  request("/api/ingestion/processing-summary");

export const processTelemetry = (limit = 500) =>
  request(`/api/ingestion/process?limit=${limit}`, {
    method: "POST",
  });
