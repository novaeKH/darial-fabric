import axios from "axios";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api";
const API_BASE_URL = import.meta.env.VITE_API_URL || DEFAULT_API_BASE_URL;

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

function unwrapData(response) {
  return response.data;
}

function normalizeNullable(value) {
  return value === undefined ? null : value;
}

async function get(path, config = {}) {
  return unwrapData(await api.get(path, config));
}

async function post(path, payload = null, config = {}) {
  return unwrapData(await api.post(path, payload, config));
}

export async function getHealth() {
  return get("/health");
}

export async function getDemoStatus() {
  return get("/demo/status");
}

export async function getDemoChecklist() {
  return get("/demo/checklist");
}

export async function resetDemo() {
  return post("/demo/reset");
}

export async function runCleanScenario() {
  return post("/demo/run-clean-scenario");
}

export async function runRiskScenario() {
  return post("/demo/run-risk-scenario");
}

export async function runSyntheticOnce() {
  return post("/synthetic/run-once");
}

export async function getAgents() {
  return get("/agents");
}

export async function getFiles(params = {}) {
  return get("/files", { params });
}

export async function getFilePassport(fileId) {
  return get(`/files/${fileId}/passport`);
}

export async function getAuditLogs(limit = 100) {
  return get("/audit", {
    params: { limit },
  });
}

export async function getSecurityFindings(params = {}) {
  return get("/security/findings", { params });
}

export async function getFlows(limit = 100) {
  return get("/flows", {
    params: { limit },
  });
}

export async function getComplianceReport() {
  return get("/reports/compliance");
}

export async function getAccessGraph() {
  return get("/graph/access");
}

export async function getLineageGraph() {
  return get("/graph/lineage");
}

export async function getPermissions(params = {}) {
  return get("/permissions", { params });
}

export async function simulatePolicy(payload) {
  return post("/policy/simulate", payload);
}

export async function scanFile(fileId, scannerAgentId = null) {
  return post("/security/scan", {
    file_id: fileId,
    scanner_agent_id: normalizeNullable(scannerAgentId),
  });
}

export async function releaseFileFromQuarantine(
  fileId,
  releasedByAgentId = null,
  reason = "Released from frontend"
) {
  return post("/security/release", {
    file_id: fileId,
    released_by_agent_id: normalizeNullable(releasedByAgentId),
    reason,
  });
}

export async function grantPermission(payload) {
  return post("/permissions/grant", payload);
}

export async function revokePermission(permissionId, revokedByAgentId = null) {
  const params = revokedByAgentId
    ? { revoked_by_agent_id: revokedByAgentId }
    : {};

  return post(`/permissions/${permissionId}/revoke`, null, { params });
}

export async function getFolders(params = {}) {
  return get("/folders", { params });
}

export async function uploadFile({ agentId, folderId, classification, file }) {
  const formData = new FormData();

  formData.append("agent_id", agentId);
  formData.append("folder_id", folderId);
  formData.append("classification", classification || "internal");
  formData.append("file", file);

  return post("/files/upload", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
}

async function extractBlobError(blob) {
  try {
    const text = await blob.text();
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export async function downloadFile(fileId, agentId) {
  try {
    const res = await api.get(`/files/${fileId}/read`, {
      params: {
        agent_id: agentId,
      },
      responseType: "blob",
    });

    return res.data;
  } catch (err) {
    const blobDetail = err?.response?.data instanceof Blob
      ? await extractBlobError(err.response.data)
      : null;

    if (blobDetail) {
      err.response.data = blobDetail;
    }

    throw err;
  }
}