import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, LogOut, UserRound } from "lucide-react";
import {
  getCurrentPrincipalId,
  getPrincipalPermissions,
  getSessionPrincipals,
  setCurrentPrincipalId,
  setCachedPermissions,
} from "./sessionApi";
import "./sessionSwitcher.css";

export default function SessionSwitcher({ onPermissionsChange }) {
  const [principals, setPrincipals] = useState([]);
  const [selected, setSelected] = useState(getCurrentPrincipalId());
  const [open, setOpen] = useState(false);

  useEffect(() => {
    getSessionPrincipals().then((rows) => setPrincipals(rows || []));
  }, []);

  const current = principals.find((item) => item.id === selected);

  async function choose(principal) {
    setCurrentPrincipalId(principal.id);
    const result = await getPrincipalPermissions(principal.id);

    setCachedPermissions(result.permissions || []);

    if (onPermissionsChange) {
      onPermissionsChange(result.permissions || []);
    }
    window.location.reload();
  }

  function logout() {
    setCurrentPrincipalId("");
    setCachedPermissions([]);

    if (onPermissionsChange) {
      onPermissionsChange([]);
    }
    window.location.reload();
  }

  return (
    <div className="session-switcher">
      <button className="session-current" onClick={() => setOpen(!open)}>
        <div className="session-avatar"><UserRound size={16} /></div>
        <div>
          <strong>{current?.display_name || "Выберите пользователя"}</strong>
          <span>{current?.email || "RBAC session"}</span>
        </div>
        <ChevronDown size={15} />
      </button>

      {open && (
        <div className="session-menu">
          {principals.filter((item) => item.status === "active").map((principal) => (
            <button key={principal.id} onClick={() => choose(principal)}>
              <div>
                <strong>{principal.display_name}</strong>
                <span>{principal.email}</span>
              </div>
              {principal.id === selected && <CheckCircle2 size={15} />}
            </button>
          ))}
          {selected && (
            <button className="session-logout" onClick={logout}>
              <LogOut size={14} /> Завершить сессию
            </button>
          )}
        </div>
      )}
    </div>
  );
}
