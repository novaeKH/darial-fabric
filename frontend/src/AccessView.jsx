import { useEffect, useState } from "react";
import {
  KeyRound,
  Plus,
  RefreshCcw,
  ShieldCheck,
  UserCheck,
  Users,
  X,
} from "lucide-react";
import {
  createAssignment,
  createPrincipal,
  deleteAssignment,
  getPrincipals,
  getRbacAudit,
  getRbacSummary,
  getRoles,
  updatePrincipalStatus,
} from "./accessApi";
import "./accessView.css";

function Metric({ icon: Icon, label, value, note, tone = "violet" }) {
  return (
    <article className={`acc-metric acc-tone-${tone}`}>
      <div className="acc-metric-icon"><Icon size={19} /></div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function UserModal({ roles, onClose, onSaved }) {
  const [form, setForm] = useState({
    email: "",
    display_name: "",
    role_id: roles[0]?.id || "",
    scope_type: "organization",
    scope_id: "",
  });
  const [error, setError] = useState("");

  async function save() {
    try {
      const principal = await createPrincipal({
        email: form.email,
        display_name: form.display_name,
      });

      if (form.role_id) {
        await createAssignment({
          principal_id: principal.id,
          role_id: form.role_id,
          scope_type: form.scope_type,
          scope_id: form.scope_type === "product" ? form.scope_id : null,
        });
      }

      await onSaved();
      onClose();
    } catch (err) {
      setError(err?.message || "Не удалось создать пользователя");
    }
  }

  return (
    <div className="acc-backdrop" onMouseDown={onClose}>
      <div className="acc-modal" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div><span>NEW PRINCIPAL</span><h3>Добавить пользователя</h3></div>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </header>

        <label>
          Имя
          <input
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
          />
        </label>

        <label>
          Email
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </label>

        <label>
          Роль
          <select
            value={form.role_id}
            onChange={(e) => setForm({ ...form, role_id: e.target.value })}
          >
            {roles.map((role) => (
              <option key={role.id} value={role.id}>{role.name}</option>
            ))}
          </select>
        </label>

        <label>
          Область действия
          <select
            value={form.scope_type}
            onChange={(e) => setForm({ ...form, scope_type: e.target.value })}
          >
            <option value="organization">Вся организация</option>
            <option value="product">Конкретный AI-продукт</option>
          </select>
        </label>

        {form.scope_type === "product" && (
          <label>
            Product ID
            <input
              value={form.scope_id}
              onChange={(e) => setForm({ ...form, scope_id: e.target.value })}
            />
          </label>
        )}

        {error && <div className="acc-error">{error}</div>}
        <button className="acc-save" type="button" onClick={save}>
          <Plus size={16} />
          Создать пользователя
        </button>
      </div>
    </div>
  );
}

export default function AccessView() {
  const [summary, setSummary] = useState({});
  const [principals, setPrincipals] = useState([]);
  const [roles, setRoles] = useState([]);
  const [audit, setAudit] = useState([]);
  const [modal, setModal] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [stats, users, roleRows, auditRows] = await Promise.all([
        getRbacSummary(),
        getPrincipals(),
        getRoles(),
        getRbacAudit(),
      ]);

      setSummary(stats || {});
      setPrincipals(Array.isArray(users) ? users : []);
      setRoles(Array.isArray(roleRows) ? roleRows : []);
      setAudit(Array.isArray(auditRows) ? auditRows : []);
    } catch (err) {
      setError(err?.message || "Ошибка загрузки доступов");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function toggleStatus(user) {
    try {
      await updatePrincipalStatus(
        user.id,
        user.status === "active" ? "disabled" : "active"
      );
      await load();
    } catch (err) {
      setError(err?.message || "Не удалось изменить статус");
    }
  }

  async function removeAssignment(id) {
    try {
      await deleteAssignment(id);
      await load();
    } catch (err) {
      setError(err?.message || "Не удалось удалить роль");
    }
  }

  return (
    <section className="acc-page">
      <header className="acc-hero">
        <div>
          <div className="acc-eyebrow">IDENTITY & ACCESS</div>
          <h2>Пользователи и роли</h2>
          <p>
            Разграничение доступа к AI-продуктам, экономике, политикам,
            нарушениям, интеграциям и аудиту.
          </p>
        </div>

        <div className="acc-actions">
          <button type="button" onClick={() => setModal(true)}>
            <Plus size={16} />
            Добавить пользователя
          </button>
          <button type="button" onClick={load}>
            <RefreshCcw size={16} />
            Обновить
          </button>
        </div>
      </header>

      {error && <div className="acc-error">{error}</div>}

      <div className="acc-metrics">
        <Metric icon={Users} label="Пользователи" value={summary.users || 0} note={`${summary.active_users || 0} активных`} />
        <Metric icon={ShieldCheck} label="Роли" value={summary.roles || 0} note="Системные профили" tone="blue" />
        <Metric icon={KeyRound} label="Назначения" value={summary.assignments || 0} note="Role bindings" tone="green" />
        <Metric icon={UserCheck} label="События аудита" value={summary.audit_events || 0} note="Изменения доступа" tone="amber" />
      </div>

      <section className="acc-panel">
        <div className="acc-panel-head">
          <h3>Пользователи</h3>
          <span>{principals.length}</span>
        </div>

        <div className="acc-users">
          {principals.map((user) => (
            <article key={user.id}>
              <div className="acc-user-main">
                <div className="acc-avatar">
                  {user.display_name.slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <strong>{user.display_name}</strong>
                  <span>{user.email}</span>
                </div>
              </div>

              <div className="acc-role-list">
                {user.assignments.map((assignment) => (
                  <button
                    type="button"
                    title="Удалить назначение"
                    onClick={() => removeAssignment(assignment.id)}
                    key={assignment.id}
                  >
                    <strong>{assignment.role_name}</strong>
                    <span>
                      {assignment.scope_type === "organization"
                        ? "Вся организация"
                        : `Продукт: ${assignment.scope_id}`}
                    </span>
                  </button>
                ))}
                {!user.assignments.length && <span>Роли не назначены</span>}
              </div>

              <button
                type="button"
                className={`acc-status acc-status-${user.status}`}
                onClick={() => toggleStatus(user)}
              >
                {user.status === "active" ? "Активен" : "Отключён"}
              </button>
            </article>
          ))}

          {!principals.length && (
            <div className="acc-empty">Пользователи пока не добавлены.</div>
          )}
        </div>
      </section>

      <section className="acc-panel">
        <div className="acc-panel-head">
          <h3>Матрица ролей</h3>
          <span>{roles.length}</span>
        </div>

        <div className="acc-role-grid">
          {roles.map((role) => (
            <article key={role.id}>
              <div>
                <span>{role.code}</span>
                <h4>{role.name}</h4>
                <p>{role.description}</p>
              </div>

              <div className="acc-permissions">
                {role.permissions.map((permission) => (
                  <span key={permission.code}>{permission.code}</span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="acc-panel">
        <div className="acc-panel-head">
          <h3>Журнал изменений доступа</h3>
          <span>{audit.length}</span>
        </div>

        <div className="acc-audit">
          {audit.map((item) => (
            <article key={item.id}>
              <strong>{item.action}</strong>
              <span>{item.principal_name || item.principal_email || "—"}</span>
              <span>{item.role_name || item.role_code || "—"}</span>
              <span>{item.actor || "system"}</span>
              <time>{new Date(item.created_at).toLocaleString("ru-RU")}</time>
            </article>
          ))}

          {!audit.length && (
            <div className="acc-empty">Изменений пока не было.</div>
          )}
        </div>
      </section>

      {modal && (
        <UserModal
          roles={roles}
          onClose={() => setModal(false)}
          onSaved={load}
        />
      )}
    </section>
  );
}
