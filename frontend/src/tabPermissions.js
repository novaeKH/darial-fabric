export const TAB_PERMISSIONS = {
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
  access: ["rbac.manage", "platform.admin"],
  audit: ["audit.read", "platform.admin"],
};

export function canAccessTab(tabId, permissions = []) {
  const required = TAB_PERMISSIONS[tabId];

  if (!required) {
    return true;
  }

  return required.some((permission) =>
    permissions.includes(permission)
  );
}
