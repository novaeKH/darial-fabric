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
    let message = text;
    try {
      const parsed = JSON.parse(text);
      message = parsed.detail || parsed.message || text;
    } catch (_) {}
    throw new Error(message || `HTTP ${response.status}`);
  }
  const text = await response.text();
  return text ? JSON.parse(text) : {};
}

const json = (method, body) => ({ method, body: JSON.stringify(body) });

export function getAiProducts() { return request("/api/ai-products"); }
export function getAgentDeployments() { return request("/api/agent-deployments"); }
export function getObservabilityRuns(limit = 500) { return request(`/api/observability/runs?limit=${limit}`); }
export function getAgentSummaries() { return request("/api/observability/agents/summary"); }
export function getRunDetails(runId) { return request(`/api/observability/runs/${encodeURIComponent(runId)}/details`); }

export function getTeams() { return request("/api/teams"); }
export function createAiProduct(payload) { return request("/api/ai-products", json("POST", payload)); }
export function createAgent(payload) { return request("/api/agents", json("POST", payload)); }
export function createAgentDeployment(payload) { return request("/api/agent-deployments", json("POST", payload)); }
export function createModelEndpoint(payload) { return request("/api/model-endpoints", json("POST", payload)); }
export function createIngestionSource(payload) { return request("/api/ingestion/sources", json("POST", payload)); }
export function createIngestionKey(sourceId, payload) {
  return request(`/api/ingestion/sources/${encodeURIComponent(sourceId)}/keys`, json("POST", payload));
}
