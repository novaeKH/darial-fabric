import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Coins,
  Download,
  FileText,
  Gauge,
  Lightbulb,
  Printer,
  RefreshCcw,
  ShieldAlert,
  Target,
  TrendingDown,
  TrendingUp,
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
const decimal = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const n = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const formatMoney = (value, currency = "RUB") => {
  if (currency === "MULTI") return `${money.format(n(value))} в разных валютах`;
  const symbol = currency === "USD" ? "$" : currency === "EUR" ? "€" : "₽";
  return `${money.format(n(value))} ${symbol}`;
};
const formatNumber = (value) => integer.format(n(value));
const formatDecimal = (value) => decimal.format(n(value));
const formatPercent = (value) => {
  if (value == null) return "—";
  return `${(n(value) * 100).toFixed(1)}%`;
};
const formatDuration = (value) =>
  value == null ? "—" : n(value) >= 1000
    ? `${(n(value) / 1000).toFixed(1)} с`
    : `${Math.round(n(value))} мс`;
const formatDate = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString("ru-RU");
};

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

function Recommendation({ tone, icon: Icon, title, children }) {
  return (
    <article className={`rep-recommendation rep-rec-${tone}`}>
      <div className="rep-rec-icon"><Icon size={17} /></div>
      <div><strong>{title}</strong><p>{children}</p></div>
    </article>
  );
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
  const policy = data?.calculation_policy || {};
  const currency = totals.currency || policy.currency || "RUB";

  const chart = useMemo(() => {
    const width = 920;
    const height = 260;
    const left = 64;
    const right = 20;
    const top = 22;
    const bottom = 42;
    const innerWidth = width - left - right;
    const innerHeight = height - top - bottom;
    const values = daily.map((item) => n(item.cost));
    const wasteValues = daily.map((item) => n(item.waste_cost));
    const maxValue = Math.max(...values, ...wasteValues, 1);
    const niceMax = Math.ceil(maxValue / Math.pow(10, Math.floor(Math.log10(maxValue)))) *
      Math.pow(10, Math.floor(Math.log10(maxValue)));
    const x = (index) =>
      left + (daily.length <= 1 ? innerWidth / 2 : (index / (daily.length - 1)) * innerWidth);
    const y = (value) => top + innerHeight - (value / niceMax) * innerHeight;
    const points = daily.map((item, index) => ({
      ...item,
      x: x(index),
      y: y(n(item.cost)),
      wasteY: y(n(item.waste_cost)),
    }));
    const line = points.map((point) => `${point.x},${point.y}`).join(" ");
    const area = points.length
      ? `${left},${top + innerHeight} ${line} ${points[points.length - 1].x},${top + innerHeight}`
      : "";
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
      value: niceMax * ratio,
      y: y(niceMax * ratio),
    }));
    const labelStep = Math.max(1, Math.ceil(daily.length / 8));
    return { width, height, left, right, top, bottom, innerWidth, innerHeight, niceMax, points, line, area, ticks, labelStep };
  }, [daily]);

  const leastEfficient = useMemo(
    () =>
      [...agents].sort((a, b) => {
        const aValue = a.cost_per_outcome ?? Number.POSITIVE_INFINITY;
        const bValue = b.cost_per_outcome ?? Number.POSITIVE_INFINITY;
        return bValue - aValue;
      }).slice(0, 5),
    [agents]
  );

  const recommendations = useMemo(() => {
    const items = [];
    if (n(totals.waste_rate) >= 0.15) {
      items.push({
        tone: "red",
        icon: TrendingDown,
        title: "Снизить потери",
        text: `На потери приходится ${formatPercent(totals.waste_rate)} расходов. Проверьте failed runs, отклонённые outcomes и повторные вызовы.`,
      });
    }
    if (n(violations.open) > 0) {
      items.push({
        tone: "amber",
        icon: ShieldAlert,
        title: "Закрыть нарушения политик",
        text: `Открыто ${formatNumber(violations.open)} нарушений, из них ${formatNumber(violations.critical)} критичных.`,
      });
    }
    if (totals.roi != null && n(totals.roi) < 0) {
      items.push({
        tone: "red",
        icon: TrendingDown,
        title: "Пересмотреть экономику",
        text: "Оценочная бизнес-ценность ниже затрат. Проверьте тарифы, частоту вызовов и корректность регистрации outcomes.",
      });
    }
    if (n(totals.successful_outcomes) === 0 && n(totals.runs) > 0) {
      items.push({
        tone: "amber",
        icon: Target,
        title: "Настроить бизнес-результаты",
        text: "Запуски есть, но полезные outcomes не зарегистрированы. Без них нельзя корректно считать стоимость результата и ROI.",
      });
    }
    if (!items.length) {
      items.push({
        tone: "green",
        icon: CheckCircle2,
        title: "Критичных отклонений нет",
        text: "Экономические и эксплуатационные показатели за выбранный период находятся в допустимом состоянии.",
      });
    }
    return items.slice(0, 3);
  }, [totals, violations]);

  return (
    <section className="rep-page">
      <div className="rep-print-meta">
        <div>
          <strong>DARIAL</strong>
          <span>Enterprise AI Control Center</span>
        </div>
        <div>
          <span>Сформировано</span>
          <strong>{new Date().toLocaleString("ru-RU")}</strong>
        </div>
      </div>

      <header className="rep-hero">
        <div>
          <div className="rep-eyebrow">УПРАВЛЕНЧЕСКАЯ ОТЧЁТНОСТЬ</div>
          <h2>Экономика и эффективность AI-систем</h2>
          <p>
            Консолидированный отчёт по расходам, бизнес-результатам,
            потерям, качеству и governance за период
            {" "}<strong>{formatDate(data?.period?.date_from || dateFrom)}</strong>
            {" — "}
            <strong>{formatDate(data?.period?.date_to || dateTo)}</strong>.
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
            <RefreshCcw size={16} className={loading ? "rep-spin" : ""} />
            Сформировать
          </button>
          <a href={managementCsvUrl(dateFrom, dateTo)}>
            <Download size={16} />
            CSV
          </a>
          <button type="button" onClick={() => window.print()}>
            <Printer size={16} />
            Печать / PDF
          </button>
        </div>
      </header>

      {error && <div className="rep-error">{error}</div>}
      {policy.currency_warning && (
        <div className="rep-error">{policy.currency_warning}</div>
      )}

      <div className="rep-metrics">
        <Metric
          icon={Coins}
          label="Общие расходы"
          value={formatMoney(totals.cost, currency)}
          note={`${formatMoney(totals.cost_per_run, currency)} на запуск`}
        />
        <Metric
          icon={Target}
          label="Стоимость результата"
          value={
            totals.cost_per_outcome == null
              ? "—"
              : formatMoney(totals.cost_per_outcome, currency)
          }
          note={`${formatDecimal(totals.successful_outcomes)} полезных результатов`}
          tone="green"
        />
        <Metric
          icon={AlertTriangle}
          label="Потери"
          value={formatMoney(totals.waste_cost, currency)}
          note={`${formatPercent(totals.waste_rate)} всех расходов`}
          tone="red"
        />
        <Metric
          icon={CircleDollarSign}
          label="Чистый эффект"
          value={formatMoney(totals.net_effect, currency)}
          note={totals.roi == null ? "ROI не рассчитан" : `ROI ${formatPercent(totals.roi)}`}
          tone={n(totals.net_effect) >= 0 ? "green" : "red"}
        />
        <Metric
          icon={Gauge}
          label="Успешность"
          value={formatPercent(totals.success_rate)}
          note={`${formatNumber(totals.failed_runs)} неуспешных запусков`}
          tone="amber"
        />
        <Metric
          icon={Zap}
          label="Использовано токенов"
          value={formatNumber(totals.tokens)}
          note={`${formatNumber(totals.runs)} запусков`}
          tone="blue"
        />
      </div>

      <div className="rep-layout">
        <section className="rep-panel rep-chart-panel">
          <div className="rep-panel-head">
            <div><BarChart3 size={18} /><h3>Динамика расходов</h3></div>
            <span>{data?.period?.days || 0} дней</span>
          </div>

          {daily.length ? (
            <div className="rep-cost-chart">
              <div className="rep-chart-legend">
                <span><i className="rep-legend-cost" />Расходы</span>
                <span><i className="rep-legend-waste" />Потери</span>
              </div>
              <svg
                viewBox={`0 0 ${chart.width} ${chart.height}`}
                role="img"
                aria-label="Динамика расходов и потерь по дням"
              >
                <defs>
                  <linearGradient id="repCostArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#7868ef" stopOpacity="0.32" />
                    <stop offset="100%" stopColor="#7868ef" stopOpacity="0.03" />
                  </linearGradient>
                </defs>

                {chart.ticks.map((tick) => (
                  <g key={tick.value}>
                    <line
                      x1={chart.left}
                      x2={chart.width - chart.right}
                      y1={tick.y}
                      y2={tick.y}
                      className="rep-chart-grid"
                    />
                    <text
                      x={chart.left - 12}
                      y={tick.y + 4}
                      textAnchor="end"
                      className="rep-chart-axis"
                    >
                      {money.format(tick.value)}
                    </text>
                  </g>
                ))}

                {chart.points.map((point, index) => {
                  const barWidth = Math.max(
                    5,
                    Math.min(18, chart.innerWidth / Math.max(chart.points.length, 1) * 0.42)
                  );
                  const showLabel =
                    index === 0 ||
                    index === chart.points.length - 1 ||
                    index % chart.labelStep === 0;
                  return (
                    <g key={point.date}>
                      <rect
                        x={point.x - barWidth / 2}
                        y={point.wasteY}
                        width={barWidth}
                        height={chart.top + chart.innerHeight - point.wasteY}
                        rx="3"
                        className="rep-chart-waste-bar"
                      >
                        <title>
                          {`${formatDate(point.date)}: потери ${formatMoney(point.waste_cost, currency)}`}
                        </title>
                      </rect>
                      {showLabel && (
                        <text
                          x={point.x}
                          y={chart.height - 14}
                          textAnchor="middle"
                          className="rep-chart-axis"
                        >
                          {point.date.slice(5)}
                        </text>
                      )}
                    </g>
                  );
                })}

                <polygon points={chart.area} fill="url(#repCostArea)" />
                <polyline points={chart.line} className="rep-chart-line" />

                {chart.points.map((point) => (
                  <circle
                    key={`point-${point.date}`}
                    cx={point.x}
                    cy={point.y}
                    r="4.5"
                    className="rep-chart-point"
                  >
                    <title>
                      {`${formatDate(point.date)}: расходы ${formatMoney(point.cost, currency)}, потери ${formatMoney(point.waste_cost, currency)}, запусков ${formatNumber(point.runs)}`}
                    </title>
                  </circle>
                ))}
              </svg>

              <div className="rep-chart-summary">
                <div>
                  <span>Средние расходы в день</span>
                  <strong>
                    {formatMoney(
                      n(totals.cost) / Math.max(n(data?.period?.days), 1),
                      currency
                    )}
                  </strong>
                </div>
                <div>
                  <span>Максимум за день</span>
                  <strong>
                    {formatMoney(
                      Math.max(...daily.map((item) => n(item.cost)), 0),
                      currency
                    )}
                  </strong>
                </div>
                <div>
                  <span>Доля потерь</span>
                  <strong>{formatPercent(totals.waste_rate)}</strong>
                </div>
              </div>
            </div>
          ) : (
            <Empty>За выбранный период данных нет.</Empty>
          )}
        </section>

        <section className="rep-panel">
          <div className="rep-panel-head">
            <div><FileText size={18} /><h3>Executive summary</h3></div>
          </div>
          <div className="rep-summary">
            <div><span>Запуски</span><strong>{formatNumber(totals.runs)}</strong></div>
            <div><span>Средняя задержка</span><strong>{formatDuration(totals.average_latency_ms)}</strong></div>
            <div><span>Полезные outcomes</span><strong>{formatDecimal(totals.successful_outcomes)}</strong></div>
            <div><span>Сэкономлено времени</span><strong>{formatNumber(totals.time_saved_minutes)} мин</strong></div>
            <div><span>Бизнес-ценность</span><strong>{formatMoney(totals.estimated_business_value, currency)}</strong></div>
            <div><span>Открытые нарушения</span><strong>{formatNumber(violations.open)}</strong></div>
            <div><span>Критичные нарушения</span><strong>{formatNumber(violations.critical)}</strong></div>
            <div><span>Валюта отчёта</span><strong>{currency}</strong></div>
          </div>
        </section>
      </div>

      <section className="rep-panel rep-recommendations-panel">
        <div className="rep-panel-head">
          <div><Lightbulb size={18} /><h3>Управленческие выводы</h3></div>
          <span>Автоматический анализ</span>
        </div>
        <div className="rep-recommendations">
          {recommendations.map((item) => (
            <Recommendation
              key={item.title}
              tone={item.tone}
              icon={item.icon}
              title={item.title}
            >
              {item.text}
            </Recommendation>
          ))}
        </div>
      </section>

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
                <th>Запуски</th>
                <th>Успешность</th>
                <th>Расходы</th>
                <th>Стоимость результата</th>
                <th>Потери</th>
                <th>Бизнес-ценность</th>
                <th>Чистый эффект</th>
                <th>ROI</th>
              </tr>
            </thead>
            <tbody>
              {products.map((item) => (
                <tr key={item.product_id}>
                  <td><strong>{item.product_name}</strong></td>
                  <td>{item.business_unit || "—"}</td>
                  <td>{formatNumber(item.runs)}</td>
                  <td>{formatPercent(item.success_rate)}</td>
                  <td>{formatMoney(item.cost, currency)}</td>
                  <td>
                    {item.cost_per_outcome == null
                      ? "Нет outcomes"
                      : formatMoney(item.cost_per_outcome, currency)}
                  </td>
                  <td>{formatMoney(item.waste_cost, currency)}</td>
                  <td>{formatMoney(item.business_value, currency)}</td>
                  <td className={n(item.net_effect) >= 0 ? "rep-positive" : "rep-negative"}>
                    {formatMoney(item.net_effect, currency)}
                  </td>
                  <td>{formatPercent(item.roi)}</td>
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
                  <span>{item.product_name} · {formatNumber(item.runs)} запусков</span>
                </div>
                <strong>{formatMoney(item.cost, currency)}</strong>
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
                      ? `${formatDecimal(item.outcomes)} полезных результатов`
                      : "Бизнес-результат не зарегистрирован"}
                  </span>
                </div>
                <strong>
                  {item.cost_per_outcome == null
                    ? "Нет данных"
                    : formatMoney(item.cost_per_outcome, currency)}
                </strong>
              </article>
            ))}
            {!agents.length && <Empty>Агенты не найдены.</Empty>}
          </div>
        </section>
      </div>

      <section className="rep-panel rep-methodology">
        <div className="rep-panel-head">
          <div><FileText size={18} /><h3>Методика расчёта</h3></div>
          <span>Версия MVP</span>
        </div>
        <div className="rep-formulas">
          <div>
            <strong>Стоимость запуска</strong>
            <code>LLM cost + tool cost + прочие зарегистрированные расходы</code>
          </div>
          <div>
            <strong>Токены</strong>
            <code>input tokens + output tokens</code>
            <small>Cached входят в input, reasoning входят в output и повторно не прибавляются.</small>
          </div>
          <div>
            <strong>Стоимость результата</strong>
            <code>общие расходы / количество полезных outcomes</code>
          </div>
          <div>
            <strong>Потери</strong>
            <code>failed/cancelled + отклонённые outcomes + зарегистрированные retry costs</code>
          </div>
          <div>
            <strong>Чистый эффект</strong>
            <code>оценочная бизнес-ценность − расходы</code>
          </div>
          <div>
            <strong>ROI</strong>
            <code>(бизнес-ценность − расходы) / расходы</code>
            <small>Бизнес-ценность и time saved являются оценочными показателями интеграции.</small>
          </div>
        </div>
      </section>

      <footer className="rep-footer">
        <span>Takt · Enterprise AI Control Center</span>
        <span>Отчёт предназначен для управленческого анализа AI-продуктов.</span>
      </footer>
    </section>
  );
}
