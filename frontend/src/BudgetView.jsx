import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDollarSign,
  Gauge,
  Pencil,
  RefreshCcw,
  Save,
  TrendingUp,
  X,
} from "lucide-react";
import {
  getBudgetSummary,
  recalculateBudgetAlerts,
  updateProductBudget,
} from "./budgetApi";
import "./budgetView.css";

import { hasPermission, permissionTitle } from "./rbacPermissions";
const money = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function n(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function formatMoney(value) {
  return `${money.format(n(value))} ₽`;
}

function formatPercent(value) {
  return `${(n(value) * 100).toFixed(1)}%`;
}

function Metric({ icon: Icon, label, value, note, tone = "violet" }) {
  return (
    <article className={`budget-metric budget-tone-${tone}`}>
      <div className="budget-metric-icon"><Icon size={19} /></div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function Status({ value }) {
  const labels = {
    healthy: "В норме",
    warning: "Предупреждение",
    critical: "Критично",
    unconfigured: "Не настроен",
  };
  return <span className={`budget-status budget-status-${value}`}>{labels[value] || value}</span>;
}

function BudgetEditor({ product, onClose, onSaved }) {
  const [amount, setAmount] = useState(product.limit_amount || 100);
  const [threshold, setThreshold] = useState((product.warning_threshold || 0.8) * 100);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true);
    setError("");
    try {
      await updateProductBudget(product.product_id, {
        limit_amount: Number(amount),
        warning_threshold: Number(threshold) / 100,
        currency: "RUB",
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(err?.message || "Не удалось сохранить бюджет");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="budget-modal-backdrop" onMouseDown={onClose}>
      <div className="budget-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="budget-modal-head">
          <div>
            <span>MONTHLY BUDGET</span>
            <h3>{product.product_name}</h3>
          </div>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </div>
        <label>
          Месячный лимит, ₽
          <input type="number" min="1" step="10" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>
          Порог предупреждения, %
          <input type="number" min="10" max="100" step="5" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
        </label>
        {error && <div className="budget-error">{error}</div>}
        <button title={permissionTitle("budgets.manage")} className="budget-save" type="button" onClick={save} disabled={(saving) || !hasPermission("budgets.manage")}>
          <Save size={16} />
          {saving ? "Сохранение…" : "Сохранить"}
        </button>
      </div>
    </div>
  );
}

export default function BudgetView() {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [alerting, setAlerting] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await getBudgetSummary());
    } catch (err) {
      setError(err?.message || "Ошибка загрузки бюджетов");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function createAlerts() {
    setAlerting(true);
    setMessage("");
    setError("");
    try {
      const result = await recalculateBudgetAlerts();
      setMessage(`Пересчитано предупреждений: ${result.created}`);
      await load();
    } catch (err) {
      setError(err?.message || "Не удалось пересчитать предупреждения");
    } finally {
      setAlerting(false);
    }
  }

  const totals = data?.totals || {};
  const counts = data?.counts || {};
  const rows = data?.products || [];

  const potentialOverspend = useMemo(
    () =>
      rows.reduce(
        (sum, product) =>
          sum + Math.max(n(product.forecast_cost) - n(product.limit_amount), 0),
        0
      ),
    [rows]
  );

  return (
    <section className="budget-page">
      <header className="budget-hero">
        <div>
          <div className="budget-eyebrow">AI FINOPS</div>
          <h2>Бюджеты и лимиты</h2>
          <p>Фактические расходы, прогноз до конца месяца и автоматические предупреждения по AI-продуктам.</p>
        </div>
        <div className="budget-actions">
          <button type="button" onClick={createAlerts} disabled={alerting}>
            <AlertTriangle size={16} />
            {alerting ? "Расчёт…" : "Пересчитать предупреждения"}
          </button>
          <button type="button" onClick={load} disabled={loading}>
            <RefreshCcw size={16} className={loading ? "budget-spin" : ""} />
            Обновить
          </button>
        </div>
      </header>

      {error && <div className="budget-error">{error}</div>}
      {message && <div className="budget-success">{message}</div>}

      <div className="budget-metrics">
        <Metric icon={CircleDollarSign} label="Общий бюджет" value={formatMoney(totals.limit_amount)} note="На текущий месяц" />
        <Metric icon={Gauge} label="Потрачено" value={formatMoney(totals.actual_cost)} note={formatPercent(totals.utilization)} tone="blue" />
        <Metric icon={TrendingUp} label="Прогноз" value={formatMoney(totals.forecast_cost)} note={formatPercent(totals.forecast_utilization)} tone="amber" />
        <Metric
          icon={potentialOverspend > 0 ? AlertTriangle : CheckCircle2}
          label="Риск превышения"
          value={formatMoney(potentialOverspend)}
          note={`${n(counts.critical)} критично · ${n(counts.warning)} предупреждений`}
          tone={potentialOverspend > 0 ? "red" : "green"}
        />
      </div>

      <div className="budget-grid">
        {rows.map((product) => {
          const actualWidth = Math.min(n(product.utilization) * 100, 100);
          const forecastWidth = Math.min(n(product.forecast_utilization) * 100, 100);
          const overspend = Math.max(
            n(product.forecast_cost) - n(product.limit_amount),
            0
          );

          return (
            <article className="budget-card" key={product.product_id}>
              <div className="budget-card-head">
                <div>
                  <span>{product.business_unit || "AI-продукт"}</span>
                  <h3>{product.product_name}</h3>
                </div>
                <Status value={product.status} />
              </div>

              <div className="budget-values">
                <div><span>Факт</span><strong>{formatMoney(product.actual_cost)}</strong></div>
                <div>
                  <span>Прогноз</span>
                  <strong>{formatMoney(product.forecast_cost)}</strong>
                  {overspend > 0 && (
                    <small className="budget-overspend">
                      +{formatMoney(overspend)} сверх бюджета
                    </small>
                  )}
                </div>
                <div><span>Бюджет</span><strong>{formatMoney(product.limit_amount)}</strong></div>
              </div>

              <div className="budget-progress-label">
                <span>Использование бюджета</span>
                <strong>{formatPercent(product.utilization)}</strong>
              </div>
              <div className="budget-progress">
                <div className="budget-progress-forecast" style={{ width: `${forecastWidth}%` }} />
                <div className={`budget-progress-actual budget-progress-${product.status}`} style={{ width: `${actualWidth}%` }} />
              </div>
              <div className="budget-legend">
                <span><i className="budget-dot-actual" />Факт</span>
                <span><i className="budget-dot-forecast" />Прогноз</span>
              </div>

              <div className="budget-card-footer">
                <span>{product.runs} запусков · потери {formatMoney(product.failed_cost)}</span>
                {hasPermission("budgets.manage") && (
                  <button type="button" onClick={() => setEditing(product)}>
                    <Pencil size={14} />
                    Настроить
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </div>

      {!loading && !rows.length && <div className="budget-empty">Бюджеты пока не настроены.</div>}
      {editing && hasPermission("budgets.manage") && (
        <BudgetEditor
          product={editing}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </section>
  );
}
