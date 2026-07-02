import { principalHeaders } from "./sessionApi";
const DEFAULT_BACKEND = `${window.location.protocol}//${window.location.hostname || "localhost"}:8000`;

function queryString(dateFrom, dateTo) {
  const query = new URLSearchParams();
  if (dateFrom) query.set("date_from", `${dateFrom}T00:00:00`);
  if (dateTo) query.set("date_to", `${dateTo}T23:59:59`);
  return query.toString();
}

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

export function getManagementReport(dateFrom, dateTo) {
  return request(
    `/api/observability/reports/management?${queryString(dateFrom, dateTo)}`
  );
}

export function managementCsvUrl(dateFrom, dateTo) {
  return `${DEFAULT_BACKEND}/api/observability/reports/management.csv?${queryString(dateFrom, dateTo)}`;
}
