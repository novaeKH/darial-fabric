import { principalHeaders } from "./sessionApi";
const DEFAULT_BACKEND = `${window.location.protocol}//${window.location.hostname || "localhost"}:8000`;

async function request(path) {
  const response = await fetch(`${DEFAULT_BACKEND}${path}`, {
    headers: principalHeaders({ Accept: "application/json" }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

export function getAiProducts() {
  return request("/api/ai-products");
}

export function getAgentDeployments() {
  return request("/api/agent-deployments");
}

export function getObservabilityRuns(limit = 500) {
  return request(`/api/observability/runs?limit=${limit}`);
}

export function getAgentSummaries() {
  return request("/api/observability/agents/summary");
}

export function getRunDetails(runId) {
  return request(`/api/observability/runs/${encodeURIComponent(runId)}/details`);
}
