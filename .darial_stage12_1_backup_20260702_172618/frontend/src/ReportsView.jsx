import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Coins,
  Download,
  Gauge,
  Printer,
  RefreshCcw,
  Target,
  Zap,
} from "lucide-react";
import {
  getManagementReport,
  managementCsvUrl,
} from "./reportsApi";
import "./reportsView.css";

const money = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const integer = new Intl.NumberFormat("ru-RU", {
  maximumFractionDigits: 0,
});

const n = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const formatMoney = (value) => `${money.format(n(value))} ₽`;
const formatNumber = (value) => integer.format(n(value));
const formatPercent = (value) => `${(n(value) * 100).toFixed(1)}%`;
const formatDuration = (value) =>
  value == null ? "—" : n(value) >= 1000
    ? `${(n(value) / 1000).toFixed(1)} с`
    : `${Math.round(n(value))} мс`;

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function Metric({ icon: Icon, label, value, note, tone = "violet" }) {
  return (
    <article className={`rep-metric rep-tone-${tone}`}>
      <div className="rep-metric-icon"><Icon size={19} /></div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function Empty({ children }) {
  return <div className="rep-empty">{children}</div>;
}

export default function ReportsView() {
  const today = new Date();
  const monthAgo = new Date();
  monthAgo.setDate(today.getDate() - 29);

  const [dateFrom, setDateFrom] = useState(isoDate(monthAgo));
  const [dateTo, setDateTo] = useState(isoDate(today));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await getManagementReport(dateFrom, dateTo));
    } catch (err) {
      setError(err?.message || "Ошибка формирования отчёта");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const totals = data?.totals || {};
  const violations = data?.violations || {};
  const products = data?.products || [];
  const agents = data?.agents || [];
  const daily = data?.daily || [];

  const maxDailyCost = useMemo(
    () => Math.max(...daily.map((item) => n(item.cost)), 1),
    [daily]
  );

  const leastEfficient = useMemo(
    () =>
      [...agents].sort((a, b) => {
        const aValue = a.cost_per_outcome ?? Number.POSITIVE_INFINITY;
        const bValue = b.cost_per_outcome ?? Number.POSITIVE_INFINITY;
        return bValue - aValue;
      }).slice(0, 5),
    [agents]
  );

  return (
    <section className="rep-page">
      <header className="rep-hero">
        <div>
          <div className="rep-eyebrow">MANAGEMENT REPORTING</div>
          <h2>Отчёты и аналитика</h2>
          <p>
            Расходы, эффективность, бизнес-результаты, SLA и нарушения
            корпоративных AI-продуктов за выбранный период.
          </p>
        </div>

        <div className="rep-actions">
          <label>
            С
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label>
            По
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
          <button type="button" onClick={load} disabled={loading}>
            <RefreshCcw size={16} />
            Сформировать
          </button>
          <a href={managementCsvUrl(dateFrom, dateTo)}>
            <Download size={16} />
            CSV
          </a>
          <button type="button" onClick={() => window.print()}>
            <Printer size={16} />
            PDF
          </button>
        </div>
      </header>

      {error && <div className="rep-error">{error}</div>}

      <div className="rep-metrics">
        <Metric
          icon={Coins}
          label="Расходы"
          value={formatMoney(totals.cost)}
          note={`${formatMoney(totals.cost_per_run)} на run`}
        />
        <Metric
          icon={Zap}
          label="Токены"
          value={formatNumber(totals.tokens)}
          note={`${formatNumber(totals.runs)} запусков`}
          tone="blue"
        />
        <Metric
          icon={Target}
          label="Стоимость результата"
          value={
            totals.cost_per_outcome == null
              ? "—"
              : formatMoney(totals.cost_per_outcome)
          }
          note={`${formatNumber(totals.successful_outcomes)} outcomes`}
          tone="green"
        />
        <Metric
          icon={Gauge}
          label="Успешность"
          value={formatPercent(totals.success_rate)}
          note={`${formatNumber(totals.failed_runs)} ошибок`}
          tone="amber"
        />
        <Metric
          icon={AlertTriangle}
          label="Нарушения"
          value={formatNumber(violations.total)}
          note={`${formatNumber(violations.critical)} критичных`}
          tone="red"
        />
      </div>

      <div className="rep-layout">
        <section className="rep-panel rep-chart-panel">
          <div className="rep-panel-head">
            <div><BarChart3 size={18} /><h3>Динамика расходов</h3></div>
            <span>{data?.period?.days || 0} дней</span>
          </div>

          {daily.length ? (
            <div className="rep-bars">
              {daily.map((item) => (
                <div className="rep-bar-item" key={item.date}>
                  <div className="rep-bar-value">{formatMoney(item.cost)}</div>
                  <div className="rep-bar-track">
                    <div
                      className="rep-bar"
                      style={{ height: `${Math.max((n(item.cost) / maxDailyCost) * 100, 3)}%` }}
                    />
                  </div>
                  <span>{item.date.slice(5)}</span>
                </div>
              ))}
            </div>
          ) : (
            <Empty>За выбранный период данных нет.</Empty>
          )}
        </section>

        <section className="rep-panel">
          <div className="rep-panel-head">
            <h3>Executive summary</h3>
          </div>
          <div className="rep-summary">
            <div>
              <span>Средняя latency</span>
              <strong>{formatDuration(totals.average_latency_ms)}</strong>
            </div>
            <div>
              <span>Успешные runs</span>
              <strong>{formatNumber(totals.successful_runs)}</strong>
            </div>
            <div>
              <span>Открытые нарушения</span>
              <strong>{formatNumber(violations.open)}</strong>
            </div>
            <div>
              <span>Стоимость run</span>
              <strong>{formatMoney(totals.cost_per_run)}</strong>
            </div>
          </div>
        </section>
      </div>

      <section className="rep-panel">
        <div className="rep-panel-head">
          <h3>AI-продукты</h3>
          <span>{products.length}</span>
        </div>

        <div className="rep-table-wrap">
          <table className="rep-table">
            <thead>
              <tr>
                <th>Продукт</th>
                <th>Подразделение</th>
                <th>Runs</th>
                <th>Успешность</th>
                <th>Токены</th>
                <th>Расходы</th>
                <th>Стоимость результата</th>
                <th>Latency</th>
              </tr>
            </thead>
            <tbody>
              {products.map((item) => (
                <tr key={item.product_id}>
                  <td><strong>{item.product_name}</strong></td>
                  <td>{item.business_unit || "—"}</td>
                  <td>{formatNumber(item.runs)}</td>
                  <td>{formatPercent(item.success_rate)}</td>
                  <td>{formatNumber(item.tokens)}</td>
                  <td>{formatMoney(item.cost)}</td>
                  <td>
                    {item.cost_per_outcome == null
                      ? "Нет outcomes"
                      : formatMoney(item.cost_per_outcome)}
                  </td>
                  <td>{formatDuration(item.average_latency_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!products.length && <Empty>Продукты не найдены.</Empty>}
        </div>
      </section>

      <div className="rep-layout">
        <section className="rep-panel">
          <div className="rep-panel-head">
            <h3>Самые дорогие агенты</h3>
          </div>
          <div className="rep-ranking">
            {agents.slice(0, 5).map((item, index) => (
              <article key={item.agent_id}>
                <span className="rep-rank">{index + 1}</span>
                <div>
                  <strong>{item.agent_name}</strong>
                  <span>{item.product_name} · {formatNumber(item.runs)} runs</span>
                </div>
                <strong>{formatMoney(item.cost)}</strong>
              </article>
            ))}
            {!agents.length && <Empty>Агенты не найдены.</Empty>}
          </div>
        </section>

        <section className="rep-panel">
          <div className="rep-panel-head">
            <h3>Низкая экономическая эффективность</h3>
          </div>
          <div className="rep-ranking">
            {leastEfficient.map((item, index) => (
              <article key={item.agent_id}>
                <span className="rep-rank">{index + 1}</span>
                <div>
                  <strong>{item.agent_name}</strong>
                  <span>
                    {item.outcomes
                      ? `${formatNumber(item.outcomes)} outcomes`
                      : "Outcome не зарегистрирован"}
                  </span>
                </div>
                <strong>
                  {item.cost_per_outcome == null
                    ? "Нет данных"
                    : formatMoney(item.cost_per_outcome)}
                </strong>
              </article>
            ))}
            {!agents.length && <Empty>Агенты не найдены.</Empty>}
          </div>
        </section>
      </div>
    </section>
  );
}
