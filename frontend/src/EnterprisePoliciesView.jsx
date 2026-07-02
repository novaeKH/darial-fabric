import { useEffect, useState } from "react";
import {
  Clock3,
  Download,
  FileJson,
  History,
  Plus,
  Save,
  Upload,
  X,
} from "lucide-react";
import {
  createCustomPolicy,
  exportPolicies,
  getPolicyAudit,
  importPolicies,
} from "./enterprisePoliciesApi";
import "./enterprisePoliciesView.css";

import { hasPermission, permissionTitle } from "./rbacPermissions";
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function CustomPolicyModal({ onClose, onSaved }) {
  const [form, setForm] = useState({
    name: "",
    code: "",
    description: "",
    field: "llm_call.input_tokens",
    operator: ">",
    value: "50000",
    severity: "warning",
    mode: "monitor",
    conditions: '{"environment":"prod"}',
  });
  const [error, setError] = useState("");

  async function save() {
    try {
      let parsedValue = form.value;
      if (!Number.isNaN(Number(form.value)) && form.value.trim() !== "") {
        parsedValue = Number(form.value);
      }
      await createCustomPolicy({
        name: form.name,
        code: form.code,
        description: form.description,
        field: form.field,
        operator: form.operator,
        value: parsedValue,
        conditions: JSON.parse(form.conditions || "{}"),
        severity: form.severity,
        mode: form.mode,
        scope_type: "organization",
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError(err?.message || "Не удалось создать правило");
    }
  }

  return (
    <div className="epol-backdrop" onMouseDown={onClose}>
      <div className="epol-modal" onMouseDown={(e) => e.stopPropagation()}>
        <header>
          <div><span>CUSTOM CONDITION</span><h3>Пользовательское правило</h3></div>
          <button onClick={onClose}><X size={18} /></button>
        </header>

        <label>Название<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Код<input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></label>
        <label>Описание<textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>

        <div className="epol-grid2">
          <label>Поле<input value={form.field} onChange={(e) => setForm({ ...form, field: e.target.value })} /></label>
          <label>Оператор
            <select value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value })}>
              {["&gt;", "&gt;=", "&lt;", "&lt;=", "==", "!=", "in", "not_in", "contains"].map((op) => (
                <option key={op} value={op.replaceAll("&gt;", ">").replaceAll("&lt;", "<")}>{op}</option>
              ))}
            </select>
          </label>
          <label>Значение<input value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} /></label>
          <label>Severity
            <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </select>
          </label>
          <label>Режим
            <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
              <option value="monitor">Monitor</option>
              <option value="block">Block</option>
            </select>
          </label>
        </div>

        <label>Дополнительные условия, JSON
          <textarea value={form.conditions} onChange={(e) => setForm({ ...form, conditions: e.target.value })} />
        </label>

        {error && <div className="epol-error">{error}</div>}
        {hasPermission("policies.manage") && (
          <button className="epol-save" onClick={save}>
            <Save size={16} />Создать правило
          </button>
        )}
      </div>
    </div>
  );
}

export default function EnterprisePoliciesView() {
  const [audit, setAudit] = useState([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);

  async function loadAudit() {
    try {
      setAudit(await getPolicyAudit());
    } catch (err) {
      setError(err?.message || "Ошибка загрузки журнала");
    }
  }

  useEffect(() => { loadAudit(); }, []);

  async function handleImport(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const result = await importPolicies(file);
      setMessage(`Импортировано политик: ${result.imported}`);
      await loadAudit();
    } catch (err) {
      setError(err?.message || "Ошибка импорта");
    } finally {
      event.target.value = "";
    }
  }

  async function handleExport(format) {
    try {
      const blob = await exportPolicies(format);
      downloadBlob(blob, `darial-policies.${format}`);
    } catch (err) {
      setError(err?.message || "Ошибка экспорта");
    }
  }

  return (
    <section className="epol-page">
      <header className="epol-hero">
        <div>
          <div className="epol-eyebrow">ENTERPRISE POLICY MANAGEMENT</div>
          <h2>Корпоративные политики</h2>
          <p>
            Импорт существующих правил компании, экспорт в Git-friendly формат,
            пользовательские условия, версии и полный журнал изменений.
          </p>
        </div>
      </header>

      {message && <div className="epol-success">{message}</div>}
      {error && <div className="epol-error">{error}</div>}

      <div className="epol-actions">
        <label className="epol-action">
          <Upload size={20} />
          <span>Импорт JSON/YAML</span>
          <small>Загрузка политик компании</small>
          <input type="file" accept=".json,.yaml,.yml" onChange={handleImport} />
        </label>

        <button className="epol-action" onClick={() => handleExport("yaml")}>
          <Download size={20} />
          <span>Экспорт YAML</span>
          <small>Для GitLab и Policy as Code</small>
        </button>

        <button className="epol-action" onClick={() => handleExport("json")}>
          <FileJson size={20} />
          <span>Экспорт JSON</span>
          <small>Для API и автоматизации</small>
        </button>

        <button className="epol-action" onClick={() => setModal(true)}>
          <Plus size={20} />
          <span>Своё условие</span>
          <small>Конструктор без изменения кода</small>
        </button>
      </div>

      <section className="epol-audit">
        <div className="epol-section-head">
          <div><History size={18} /><h3>Журнал изменений</h3></div>
          <span>{audit.length}</span>
        </div>

        <div className="epol-audit-list">
          {audit.map((item) => (
            <article key={item.id}>
              <div className="epol-audit-icon"><Clock3 size={15} /></div>
              <div>
                <strong>{item.action}</strong>
                <span>{item.actor || "system"}</span>
              </div>
              <code>{item.policy_id || "—"}</code>
              <time>{new Date(item.created_at).toLocaleString("ru-RU")}</time>
            </article>
          ))}
          {!audit.length && <div className="epol-empty">Записей пока нет.</div>}
        </div>
      </section>

      {modal && <CustomPolicyModal onClose={() => setModal(false)} onSaved={loadAudit} />}
    </section>
  );
}
