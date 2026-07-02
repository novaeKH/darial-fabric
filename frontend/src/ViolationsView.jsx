import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  ExternalLink,
  Filter,
  ShieldAlert,
} from "lucide-react";
import {
  getViolations,
  getViolationSummary,
  updateViolationStatus,
} from "./violationsApi";
import RunViolationDrawer from "./RunViolationDrawer";
import "./violationsView.css";

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function SeverityBadge({ value }) {
  const labels = {
    critical: "Критично",
    warning: "Предупреждение",
    info: "Информация",
  };
  return (
    <span className={`viol-severity viol-severity-${value}`}>
      {labels[value] || value}
    </span>
  );
}

function StatusBadge({ value }) {
  const labels = {
    open: "Открыто",
    acknowledged: "Принято",
    resolved: "Закрыто",
  };
  return (
    <span className={`viol-status viol-status-${value}`}>
      {labels[value] || value}
    </span>
  );
}

function Metric({ icon: Icon, label, value, note, tone = "violet" }) {
  return (
    <article className={`viol-metric viol-tone-${tone}`}>
      <div className="viol-metric-icon"><Icon size={19} /></div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}


function BudgetDetails({ item }) {
  if (!String(item.policy_code || "").startsWith("BUDGET_")) return null;
  const d = item.details || {};
  const actual = Number(d.actual_cost || 0);
  const forecast = Number(d.forecast_cost || 0);
  const limit = Number(d.limit_amount || 0);
  const over = Math.max(forecast - limit, actual - limit, 0);
  const money = (v) => `${v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
  return <div className="viol-budget-details">
    <div><span>Факт</span><strong>{money(actual)}</strong></div>
    <div><span>Прогноз</span><strong>{money(forecast)}</strong></div>
    <div><span>Лимит</span><strong>{money(limit)}</strong></div>
    <div><span>Риск превышения</span><strong className={over > 0 ? "viol-over" : ""}>{money(over)}</strong></div>
  </div>;
}

export default function ViolationsView() {
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState({});
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState(null);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [rows, stats] = await Promise.all([
        getViolations({ status, severity, limit: 300 }),
        getViolationSummary(),
      ]);
      setItems(Array.isArray(rows) ? rows : []);
      setSummary(stats || {});
    } catch (err) {
      setError(err?.message || "Ошибка загрузки нарушений");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [status, severity]);

  async function changeStatus(id, nextStatus) {
    setWorkingId(id);
    setError("");
    try {
      await updateViolationStatus(id, nextStatus);
      await load();
    } catch (err) {
      setError(err?.message || "Не удалось изменить статус");
    } finally {
      setWorkingId(null);
    }
  }

  const grouped = useMemo(() => {
    const result = {};
    for (const item of items) {
      const key = item.product_name || "Без продукта";
      if (!result[key]) result[key] = [];
      result[key].push(item);
    }
    return Object.entries(result);
  }, [items]);

  return (
    <section className="viol-page">
      <header className="viol-hero">
        <div>
          <div className="viol-eyebrow">AI GOVERNANCE</div>
          <h2>Нарушения и предупреждения</h2>
          <p>
            Бюджетные риски, excessive retries, аномальные расходы и другие
            события, требующие внимания владельца AI-платформы.
          </p>
        </div>

      </header>

      {error && <div className="viol-error">{error}</div>}

      <div className="viol-metrics">
        <Metric icon={ShieldAlert} label="Открытые" value={summary.open || 0} note="Требуют внимания" tone="red" />
        <Metric icon={AlertTriangle} label="Критичные" value={summary.critical || 0} note="Высший приоритет" tone="amber" />
        <Metric icon={CircleAlert} label="Предупреждения" value={summary.warning || 0} note="Средний приоритет" tone="blue" />
        <Metric icon={CheckCircle2} label="Закрытые" value={summary.resolved || 0} note="Уже обработаны" tone="green" />
      </div>

      <div className="viol-filters">
        <div>
          <Filter size={16} />
          <strong>Фильтры</strong>
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Все статусы</option>
          <option value="open">Открытые</option>
          <option value="acknowledged">Принятые</option>
          <option value="resolved">Закрытые</option>
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">Любая критичность</option>
          <option value="critical">Критичные</option>
          <option value="warning">Предупреждения</option>
          <option value="info">Информационные</option>
        </select>
      </div>

      <div className="viol-groups">
        {grouped.map(([productName, rows]) => (
          <section className="viol-group" key={productName}>
            <div className="viol-group-head">
              <h3>{productName}</h3>
              <span>{rows.length}</span>
            </div>

            <div className="viol-list">
              {rows.map((item) => (
                <article className="viol-card" key={item.id}>
                  <div className="viol-card-main">
                    <div className="viol-card-top">
                      <SeverityBadge value={item.severity} />
                      <StatusBadge value={item.status} />
                      <span className="viol-code">{item.policy_code}</span>
                    </div>

                    <h4>{item.description}</h4>

                    <BudgetDetails item={item} />

                    <div className="viol-meta">
                      <span>{formatDate(item.detected_at)}</span>
                      {item.agent_name && <span>Агент: {item.agent_name}</span>}
                      {item.workflow_name && <span>Workflow: {item.workflow_name}</span>}
                      {item.trace_id && <span>Trace: {item.trace_id}</span>}
                    </div>
                  </div>

                  <div className="viol-actions">
                    {item.run_id && (
                      <button
                        type="button"
                        className="viol-secondary"
                        title="Открыть связанный run"
                        onClick={() => setSelectedRunId(item.run_id)}
                      >
                        <ExternalLink size={14} />
                        Run
                      </button>
                    )}

                    {item.status !== "acknowledged" && item.status !== "resolved" && (
                      <button
                        type="button"
                        className="viol-secondary"
                        disabled={workingId === item.id}
                        onClick={() => changeStatus(item.id, "acknowledged")}
                      >
                        Принять
                      </button>
                    )}

                    {item.status !== "resolved" && (
                      <button
                        type="button"
                        className="viol-primary"
                        disabled={workingId === item.id}
                        onClick={() => changeStatus(item.id, "resolved")}
                      >
                        Закрыть
                      </button>
                    )}

                    {item.status === "resolved" && (
                      <button
                        type="button"
                        className="viol-secondary"
                        disabled={workingId === item.id}
                        onClick={() => changeStatus(item.id, "open")}
                      >
                        Открыть снова
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>

      {!loading && !items.length && (
        <div className="viol-empty">По выбранным фильтрам нарушений нет.</div>
      )}

      {selectedRunId && (
        <RunViolationDrawer runId={selectedRunId} onClose={() => setSelectedRunId(null)} />
      )}
    </section>
  );
}
