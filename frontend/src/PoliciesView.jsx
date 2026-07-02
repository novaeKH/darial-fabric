import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  CheckCircle2,
  Gauge,
  Plus,
  RefreshCcw,
  Save,
  ShieldCheck,
  ToggleLeft,
  ToggleRight,
  X,
} from "lucide-react";
import {
  createPolicy,
  evaluatePolicies,
  getPolicies,
  updatePolicy,
} from "./policiesApi";
import "./policiesView.css";

import { hasPermission, permissionTitle } from "./rbacPermissions";
const RULE_LABELS = {
  max_run_cost: "Стоимость run",
  max_latency_ms: "Latency",
  require_outcome: "Business outcome",
  allowed_models: "Разрешённые модели",
  prohibited_tools: "Запрещённые инструменты",
  max_retries: "Retries",
};

function Metric({ icon: Icon, label, value, note, tone = "violet" }) {
  return (
    <article className={`pol-metric pol-tone-${tone}`}>
      <div className="pol-metric-icon"><Icon size={19} /></div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function Badge({ type, value }) {
  const labels = {
    monitor: "Monitor",
    block: "Block",
    info: "Info",
    warning: "Warning",
    critical: "Critical",
  };
  return (
    <span className={`pol-badge pol-badge-${type}-${value}`}>
      {labels[value] || value}
    </span>
  );
}

function configSummary(policy) {
  const config = policy.config || {};
  switch (policy.rule_type) {
    case "max_run_cost":
      return `Лимит: ${config.limit ?? "—"} ₽`;
    case "max_latency_ms":
      return `Лимит: ${config.limit ?? "—"} мс`;
    case "require_outcome":
      return "Outcome обязателен";
    case "allowed_models":
      return `${config.models?.length || 0} разрешённых моделей`;
    case "prohibited_tools":
      return `${config.tools?.length || 0} запрещённых инструментов`;
    case "max_retries":
      return `Максимум: ${config.limit ?? "—"} retries`;
    default:
      return "Конфигурация";
  }
}

function PolicyEditor({ onClose, onSaved }) {
  const [form, setForm] = useState({
    name: "",
    code: "",
    description: "",
    rule_type: "max_run_cost",
    severity: "warning",
    mode: "monitor",
    scope_type: "organization",
    configValue: "2.5",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function configFromForm() {
    if (form.rule_type === "require_outcome") return {};
    if (form.rule_type === "allowed_models") {
      return { models: form.configValue.split(",").map((x) => x.trim()).filter(Boolean) };
    }
    if (form.rule_type === "prohibited_tools") {
      return { tools: form.configValue.split(",").map((x) => x.trim()).filter(Boolean) };
    }
    return { limit: Number(form.configValue) };
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      await createPolicy({
        name: form.name,
        code: form.code,
        description: form.description,
        rule_type: form.rule_type,
        severity: form.severity,
        mode: form.mode,
        scope_type: form.scope_type,
        config: configFromForm(),
        is_enabled: true,
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError(err?.message || "Не удалось создать политику");
    } finally {
      setSaving(false);
    }
  }

  const listRule = ["allowed_models", "prohibited_tools"].includes(form.rule_type);

  return (
    <div className="pol-modal-backdrop" onMouseDown={onClose}>
      <div className="pol-modal" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div><span>NEW POLICY</span><h3>Создать политику</h3></div>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </header>

        <label>Название<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Код<input placeholder="MAX_SINGLE_RUN_COST" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></label>
        <label>Описание<textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>

        <div className="pol-form-grid">
          <label>Тип правила
            <select value={form.rule_type} onChange={(e) => setForm({ ...form, rule_type: e.target.value, configValue: "" })}>
              {Object.entries(RULE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
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
          <label>Scope
            <select value={form.scope_type} onChange={(e) => setForm({ ...form, scope_type: e.target.value })}>
              <option value="organization">Организация</option>
              <option value="product">Продукт</option>
            </select>
          </label>
        </div>

        {form.rule_type !== "require_outcome" && (
          <label>
            {listRule ? "Значения через запятую" : "Лимит"}
            <input value={form.configValue} onChange={(e) => setForm({ ...form, configValue: e.target.value })} />
          </label>
        )}

        {error && <div className="pol-error">{error}</div>}
        <button title={permissionTitle("policies.manage")} className="pol-save" type="button" onClick={save} disabled={(saving) || !hasPermission("policies.manage")}>
          <Save size={16} />{saving ? "Сохранение…" : "Создать политику"}
        </button>
      </div>
    </div>
  );
}

export default function PoliciesView() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const rows = await getPolicies();
      setItems(Array.isArray(rows) ? rows : []);
    } catch (err) {
      setError(err?.message || "Ошибка загрузки политик");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function toggle(policy) {
    try {
      await updatePolicy(policy.id, { is_enabled: !policy.is_enabled });
      await load();
    } catch (err) {
      setError(err?.message || "Не удалось изменить политику");
    }
  }

  async function evaluate() {
    setEvaluating(true);
    setMessage("");
    setError("");
    try {
      const result = await evaluatePolicies();
      setMessage(
        `Проверено runs: ${result.checked_runs}. Создано нарушений: ${result.created}.`
      );
    } catch (err) {
      setError(err?.message || "Не удалось выполнить проверку");
    } finally {
      setEvaluating(false);
    }
  }

  const stats = useMemo(() => ({
    enabled: items.filter((x) => x.is_enabled).length,
    block: items.filter((x) => x.is_enabled && x.mode === "block").length,
    critical: items.filter((x) => x.is_enabled && x.severity === "critical").length,
  }), [items]);

  return (
    <section className="pol-page">
      <header className="pol-hero">
        <div>
          <div className="pol-eyebrow">AI POLICY ENGINE</div>
          <h2>Политики и правила</h2>
          <p>
            Управляемые ограничения для стоимости, latency, моделей, инструментов,
            retries и обязательных бизнес-результатов.
          </p>
        </div>
        <div className="pol-actions">
          {hasPermission("policies.manage") && (
            <button type="button" onClick={evaluate} disabled={evaluating}>
              <Activity size={16} />{evaluating ? "Проверка…" : "Проверить runs"}
            </button>
          )}
          {hasPermission("policies.manage") && (
            <button type="button" onClick={() => setEditorOpen(true)}>
              <Plus size={16} />Создать
            </button>
          )}
          <button type="button" onClick={load} disabled={loading}>
            <RefreshCcw size={16} />Обновить
          </button>
        </div>
      </header>

      {error && <div className="pol-error">{error}</div>}
      {message && <div className="pol-success">{message}</div>}

      <div className="pol-metrics">
        <Metric icon={ShieldCheck} label="Активные политики" value={stats.enabled} note={`Всего: ${items.length}`} />
        <Metric icon={Ban} label="Режим Block" value={stats.block} note="Предотвращают выполнение" tone="red" />
        <Metric icon={AlertTriangle} label="Critical" value={stats.critical} note="Высший приоритет" tone="amber" />
        <Metric icon={Gauge} label="Покрытие" value={`${Object.keys(RULE_LABELS).length} типов`} note="Контролируемых правил" tone="blue" />
      </div>

      <div className="pol-grid">
        {items.map((policy) => (
          <article className={`pol-card ${!policy.is_enabled ? "pol-disabled" : ""}`} key={policy.id}>
            <div className="pol-card-head">
              <div>
                <span>{policy.code}</span>
                <h3>{policy.name}</h3>
              </div>
              {hasPermission("policies.manage") ? (
                <button className="pol-toggle" type="button" onClick={() => toggle(policy)}>
                  {policy.is_enabled ? <ToggleRight size={32} /> : <ToggleLeft size={32} />}
                </button>
              ) : (
                <span className="pol-readonly-state">
                  {policy.is_enabled ? "Включена" : "Отключена"}
                </span>
              )}
            </div>

            <p>{policy.description || "Описание отсутствует."}</p>

            <div className="pol-badges">
              <Badge type="mode" value={policy.mode} />
              <Badge type="severity" value={policy.severity} />
              <span className="pol-scope">
                {policy.scope_type === "organization" ? "Вся организация" : "AI-продукт"}
              </span>
            </div>

            <div className="pol-rule">
              <span>{RULE_LABELS[policy.rule_type] || policy.rule_type}</span>
              <strong>{configSummary(policy)}</strong>
            </div>

            <footer>
              <span>{policy.is_enabled ? "Политика включена" : "Политика отключена"}</span>
              {policy.mode === "block" ? <Ban size={15} /> : <CheckCircle2 size={15} />}
            </footer>
          </article>
        ))}
      </div>

      {!loading && !items.length && <div className="pol-empty">Политики пока не созданы.</div>}
      {editorOpen && hasPermission("policies.manage") && (
        <PolicyEditor onClose={() => setEditorOpen(false)} onSaved={load} />
      )}
    </section>
  );
}
