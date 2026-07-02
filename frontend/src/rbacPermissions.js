import { getCachedPermissions } from "./sessionApi";

export function hasPermission(permission) {
  const permissions = getCachedPermissions();
  return permissions.includes("platform.admin") || permissions.includes(permission);
}

export function permissionTitle(permission) {
  return hasPermission(permission)
    ? undefined
    : "У выбранной роли нет разрешения на это действие";
}
