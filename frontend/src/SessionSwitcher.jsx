import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, LogOut, ShieldCheck, UserRound } from "lucide-react";
import "./sessionSwitcher.css";
import {
  clearRbacSession,
  getCurrentPrincipalId,
  getPrincipalPermissions,
  getSessionPrincipals,
  setCachedPermissions,
  setCurrentPrincipalId,
} from "./sessionApi";

export default function SessionSwitcher({ onPermissionsChange }) {
  const [principals, setPrincipals] = useState([]);
  const [selected, setSelected] = useState(getCurrentPrincipalId());
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const current = useMemo(
    () => principals.find((item) => item.id === selected),
    [principals, selected]
  );

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      setLoading(true);
      setError("");
      try {
        const rows = await getSessionPrincipals();
        if (cancelled) return;
        const activeRows = Array.isArray(rows)
          ? rows.filter((item) => item.status === "active")
          : [];
        setPrincipals(activeRows);

        const storedId = getCurrentPrincipalId();
        const storedPrincipal = activeRows.find((item) => item.id === storedId);

        if (!storedPrincipal) {
          clearRbacSession();
          setSelected("");
          onPermissionsChange?.([]);
          return;
        }

        // Always refresh permissions from backend on page load.
        const result = await getPrincipalPermissions(storedId);
        if (cancelled) return;
        const permissions = Array.isArray(result?.permissions)
          ? result.permissions
          : [];
        setCachedPermissions(permissions, storedId);
        setSelected(storedId);
        onPermissionsChange?.(permissions);
      } catch (err) {
        if (cancelled) return;
        clearRbacSession();
        setSelected("");
        onPermissionsChange?.([]);
        setError(err?.message === "HTTP 404" ? "Backend RBAC API не найден" : (err?.message || "Не удалось загрузить RBAC-сессию"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  async function choose(principal) {
    setLoading(true);
    setError("");

    // Clear the previous role before requesting the new one. This prevents
    // a one-frame admin permission leak in the navigation.
    setCachedPermissions([], principal.id);
    setCurrentPrincipalId(principal.id);
    setSelected(principal.id);
    onPermissionsChange?.([]);

    try {
      const result = await getPrincipalPermissions(principal.id);
      const permissions = Array.isArray(result?.permissions)
        ? result.permissions
        : [];
      setCachedPermissions(permissions, principal.id);
      onPermissionsChange?.(permissions);
      setOpen(false);
    } catch (err) {
      clearRbacSession();
      setSelected("");
      onPermissionsChange?.([]);
      setError(err?.message || "Не удалось переключить роль");
    } finally {
      setLoading(false);
    }
  }

  function logout() {
    clearRbacSession();
    setSelected("");
    onPermissionsChange?.([]);
    setOpen(false);
  }

  return (
    <div className="session-switcher">
      <button
        type="button"
        className="session-current"
        onClick={() => setOpen((value) => !value)}
        disabled={loading}
        aria-expanded={open}
      >
        <div className="session-avatar"><UserRound size={16} /></div>
        <div>
          <strong>{current?.display_name || (loading ? "Проверка доступа…" : "Выберите роль")}</strong>
          <span>{current?.email || "RBAC session"}</span>
        </div>
        <ChevronDown size={15} />
      </button>

      {open && (
        <div className="session-menu">
          <div className="session-menu-title">
            <ShieldCheck size={15} />
            Действовать от имени
          </div>

          {principals.map((principal) => (
            <button
              type="button"
              key={principal.id}
              onClick={() => choose(principal)}
              disabled={loading}
            >
              <div>
                <strong>{principal.display_name}</strong>
                <span>{principal.email}</span>
              </div>
              {principal.id === selected && <CheckCircle2 size={15} />}
            </button>
          ))}

          {selected && (
            <button type="button" className="session-logout" onClick={logout}>
              <LogOut size={15} />
              Завершить сессию
            </button>
          )}

          {error && <div className="session-error">{error}</div>}
        </div>
      )}
    </div>
  );
}
