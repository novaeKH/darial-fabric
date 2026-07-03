export const TAB_PERMISSIONS = Object.freeze({
  economics: ["economics.read", "platform.admin"],
  "ai-products": ["products.read", "platform.admin"],
  "ai-agents": ["products.read", "runs.read", "platform.admin"],
  "agent-runs": ["runs.read", "platform.admin"],
  budgets: ["budgets.read", "platform.admin"],
  violations: ["violations.read", "platform.admin"],
  policies: ["policies.read", "platform.admin"],
  "enterprise-policies": ["policies.manage", "platform.admin"],
  integrations: ["integrations.manage", "platform.admin"],
  reports: ["reports.read", "platform.admin"],
  dlq: ["integrations.manage", "platform.admin"],
  access: ["rbac.manage", "platform.admin"],
  audit: ["audit.read", "platform.admin"],

  // Legacy Takt screens are explicitly protected too. Unknown tabs are
  // denied rather than displayed by default.
  dashboard: ["platform.admin"],
  agents: ["platform.admin"],
  files: ["platform.admin"],
  upload: ["platform.admin"],
  policy: ["platform.admin"],
  passport: ["platform.admin"],
  permissions: ["platform.admin"],
  security: ["platform.admin"],
  graph: ["platform.admin"],
  flows: ["platform.admin"],
});

export function canAccessTab(tabId, permissions = []) {
  const granted = new Set(Array.isArray(permissions) ? permissions : []);
  if (granted.has("platform.admin")) return true;

  const required = TAB_PERMISSIONS[tabId];
  if (!required) return false;

  return required.some((permission) => granted.has(permission));
}

export function firstAccessibleTab(tabs, permissions = []) {
  return tabs.find((tab) => canAccessTab(tab.id, permissions))?.id || null;
}
