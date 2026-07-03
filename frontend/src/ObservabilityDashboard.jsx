import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Bot,
  Coins,
  Gauge,
  RefreshCcw,
  Sparkles,
  Target,
  Timer,
  WalletCards,
  Zap,
} from "lucide-react";
import "./observability.css";
import {
  getAgentDeployments,
  getAiProducts,
  getObservabilityRuns,
  getObservabilitySummary,
} from "./observabilityApi";

const money = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const integer = new Intl.NumberFormat("ru-RU", {
  maximumFractionDigits: 0,
});

function n(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function firstValue(object, keys, fallback = 0) {
  for (const key of keys) {
    if (object?.[key] !== undefined && object?.[key] !== null) {
      return object[key];
    }
  }
  return fallback;
}

function runCost(run) {
  return n(firstValue(run, ["estimated_cost", "total_cost", "cost", "calculated_cost"]));
}

function runTokens(run) {
  const total = n(firstValue(run, ["total_tokens"]));
  if (total > 0) return total;

  // Cached tokens are included in input tokens, and reasoning tokens are
  // included in output tokens. They are displayed separately in details,
  // but must not be counted twice in the run total.
  return n(run.input_tokens) + n(run.output_tokens);
}

function runDate(run) {
  return firstValue(run, ["started_at", "created_at", "finished_at"], null);
}

function formatMoney(value) {
  return `${money.format(n(value))} ₽`;
}

function formatCompact(value) {
  const number = n(value);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)} млн`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)} тыс.`;
  return integer.format(number);
}

function formatPercent(value) {
  const number = n(value);
  const percent = number <= 1 ? number * 100 : number;
  return `${percent.toFixed(1)}%`;
}

function formatDuration(value) {
  const ms = n(value);
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} с`;
  return `${Math.round(ms)} мс`;
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function StatCard({ title, value, subtitle, icon: Icon, tone = "neutral", trend }) {
  return (
    <article className={`obs-stat obs-tone-${tone}`}>
      <div className="obs-stat-head">
        <div className="obs-stat-icon"><Icon size={19} /></div>
        {trend && (
          <span className={`obs-trend ${trend.kind === "bad" ? "obs-trend-bad" : "obs-trend-good"}`}>
            {trend.direction === "down" ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />}
            {trend.label}
          </span>
        )}
      </div>
      <div className="obs-stat-title">{title}</div>
      <div className="obs-stat-value">{value}</div>
      <div className="obs-stat-subtitle">{subtitle}</div>
    </article>
  );
}

function CostTrend({ points }) {
  if (!points.length) return <div className="obs-empty">Нет данных для графика.</div>;

  const width = 920;
  const height = 250;
  const padding = 28;
  const max = Math.max(...points.map((item) => item.cost), 1);
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;

  const coordinates = points.map((item, index) => {
    const x = padding + (index / Math.max(points.length - 1, 1)) * usableWidth;
    const y = height - padding - (item.cost / max) * usableHeight;
    return { ...item, x, y };
  });
  const line = coordinates.map((point) => `${point.x},${point.y}`).join(" ");
  const area = `${padding},${height - padding} ${line} ${width - padding},${height - padding}`;

  return (
    <div className="obs-chart-wrap">
      <svg className="obs-line-chart" viewBox={`0 0 ${width} ${height}`} role="img">
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = height - padding - ratio * usableHeight;
          return <line key={ratio} x1={padding} x2={width - padding} y1={y} y2={y} className="obs-grid-line" />;
        })}
        <polygon points={area} className="obs-area" />
        <polyline points={line} className="obs-line" />
        {coordinates.map((point) => (
          <circle key={point.key} cx={point.x} cy={point.y} r="3.5" className="obs-dot">
            <title>{`${point.label}: ${formatMoney(point.cost)}`}</title>
          </circle>
        ))}
      </svg>
      <div className="obs-chart-labels">
        {coordinates.filter((_, i) => i === 0 || i === coordinates.length - 1 || i % 5 === 0).map((point) => (
          <span key={point.key}>{point.shortLabel}</span>
        ))}
      </div>
    </div>
  );
}

function StatusDonut({ successful, failed }) {
  const total = successful + failed;
  const success = total ? (successful / total) * 100 : 0;
  return (
    <div className="obs-donut-layout">
      <div
        className="obs-donut"
        style={{ background: `conic-gradient(var(--obs-green) 0 ${success}%, var(--obs-red) ${success}% 100%)` }}
      >
        <div className="obs-donut-center">
          <strong>{formatPercent(success)}</strong>
          <span>успешно</span>
        </div>
      </div>
      <div className="obs-legend">
        <div><i className="obs-legend-success" /><span>Успешные</span><strong>{integer.format(successful)}</strong></div>
        <div><i className="obs-legend-failed" /><span>Ошибки</span><strong>{integer.format(failed)}</strong></div>
      </div>
    </div>
  );
}

function HorizontalBars({ rows }) {
  const max = Math.max(...rows.map((row) => row.cost), 1);
  return (
    <div className="obs-bars">
      {rows.map((row) => (
        <div className="obs-bar-row" key={row.key}>
          <div className="obs-bar-meta">
            <span title={row.label}>{row.label}</span>
            <strong>{formatMoney(row.cost)}</strong>
          </div>
          <div className="obs-bar-track">
            <div className="obs-bar-fill" style={{ width: `${Math.max((row.cost / max) * 100, 2)}%` }} />
          </div>
          <div className="obs-bar-note">{integer.format(row.runs)} запусков · {formatCompact(row.tokens)} токенов</div>
        </div>
      ))}
    </div>
  );
}

function Recommendation({ type, title, text, value }) {
  return (
    <article className={`obs-recommendation obs-recommendation-${type}`}>
      <div className="obs-recommendation-icon">
        {type === "warning" ? <AlertTriangle size={18} /> : <Sparkles size={18} />}
      </div>
      <div>
        <div className="obs-recommendation-title">{title}</div>
        <p>{text}</p>
      </div>
      {value && <strong>{value}</strong>}
    </article>
  );
}

export default function ObservabilityDashboard() {
  const [summary, setSummary] = useState(null);
  const [runs, setRuns] = useState([]);
  const [products, setProducts] = useState([]);
  const [deployments, setDeployments] = useState([]);
  const [period, setPeriod] = useState("30");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [summaryData, runsData, productsData, deploymentsData] = await Promise.all([
        getObservabilitySummary(),
        getObservabilityRuns(500),
        getAiProducts().catch(() => []),
        getAgentDeployments().catch(() => []),
      ]);
      setSummary(summaryData || {});
      setRuns(Array.isArray(runsData) ? runsData : runsData?.items || []);
      setProducts(Array.isArray(productsData) ? productsData : productsData?.items || []);
      setDeployments(Array.isArray(deploymentsData) ? deploymentsData : deploymentsData?.items || []);
    } catch (err) {
      setError(err?.message || "Не удалось загрузить данные observability");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const productById = useMemo(() => {
    const map = {};
    products.forEach((product) => { map[product.id] = product.name || product.title || product.id; });
    return map;
  }, [products]);

  const deploymentById = useMemo(() => {
    const map = {};
    deployments.forEach((deployment) => { map[deployment.id] = deployment; });
    return map;
  }, [deployments]);

  const filteredRuns = useMemo(() => {
    const days = Number(period);
    if (!Number.isFinite(days)) return runs;
    const threshold = Date.now() - days * 24 * 60 * 60 * 1000;
    return runs.filter((run) => {
      const value = runDate(run);
      return !value || new Date(value).getTime() >= threshold;
    });
  }, [runs, period]);

  const daily = useMemo(() => {
    const groups = new Map();
    filteredRuns.forEach((run) => {
      const value = runDate(run);
      if (!value) return;
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return;
      const key = date.toISOString().slice(0, 10);
      const current = groups.get(key) || { key, cost: 0, runs: 0 };
      current.cost += runCost(run);
      current.runs += 1;
      groups.set(key, current);
    });
    return [...groups.values()]
      .sort((a, b) => a.key.localeCompare(b.key))
      .map((item) => {
        const date = new Date(`${item.key}T12:00:00`);
        return {
          ...item,
          label: date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" }),
          shortLabel: date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }),
        };
      });
  }, [filteredRuns]);

  const agentRows = useMemo(() => {
    const groups = new Map();
    filteredRuns.forEach((run) => {
      const deployment = deploymentById[run.deployment_id];
      const key = run.agent_id || deployment?.agent_id || run.deployment_id || "unknown";
      const label =
        run.agent_name ||
        deployment?.name ||
        deployment?.service_name ||
        deployment?.agent_name ||
        String(key).slice(0, 18);
      const current = groups.get(key) || { key, label, cost: 0, tokens: 0, runs: 0 };
      current.cost += runCost(run);
      current.tokens += runTokens(run);
      current.runs += 1;
      groups.set(key, current);
    });
    return [...groups.values()].sort((a, b) => b.cost - a.cost).slice(0, 6);
  }, [filteredRuns, deploymentById]);

  const localTotals = useMemo(() => {
    const successful = filteredRuns.filter((run) =>
      ["success", "completed", "ok"].includes(String(run.status || "").toLowerCase())
    ).length;
    const failed = filteredRuns.filter((run) =>
      ["failed", "error", "cancelled"].includes(String(run.status || "").toLowerCase())
    ).length;
    return {
      runs: filteredRuns.length,
      successful,
      failed,
      cost: filteredRuns.reduce((sum, run) => sum + runCost(run), 0),
      tokens: filteredRuns.reduce((sum, run) => sum + runTokens(run), 0),
    };
  }, [filteredRuns]);

  const totalRuns = period === "30" ? n(summary?.total_runs) || localTotals.runs : localTotals.runs;
  const successfulRuns = period === "30" ? n(summary?.successful_runs) || localTotals.successful : localTotals.successful;
  const failedRuns = period === "30" ? n(summary?.failed_runs) || localTotals.failed : localTotals.failed;
  const totalCost = period === "30" ? n(summary?.total_cost) || localTotals.cost : localTotals.cost;
  const totalTokens = period === "30" ? n(summary?.total_tokens) || localTotals.tokens : localTotals.tokens;
  const wasteRate = n(summary?.waste_rate);
  const failedCost = n(summary?.failed_run_cost);
  const costPerOutcome = summary?.cost_per_outcome;
  const averageLatency = summary?.average_latency_ms;
  const successfulOutcomes = n(summary?.successful_outcomes);

  const forecast = daily.length
    ? (daily.reduce((sum, item) => sum + item.cost, 0) / daily.length) * 30
    : totalCost;

  const recommendations = [
    wasteRate >= 0.05
      ? {
          type: "warning",
          title: "Снизить расходы на неуспешные запуски",
          text: `${formatPercent(wasteRate)} расходов приходится на ошибки и бесполезные выполнения.`,
          value: `Потери ${formatMoney(failedCost)}`,
        }
      : {
          type: "good",
          title: "Уровень потерь под контролем",
          text: "Доля расходов на неуспешные запуски остаётся ниже порогового значения 5%.",
          value: formatPercent(wasteRate),
        },
    {
      type: "good",
      title: "Контролировать стоимость бизнес-результата",
      text: `Получено ${integer.format(successfulOutcomes)} подтверждённых полезных результатов.`,
      value: costPerOutcome == null ? "Нет оценки" : formatMoney(costPerOutcome),
    },
    {
      type: forecast > totalCost * 1.15 ? "warning" : "good",
      title: "Прогноз расходов на 30 дней",
      text: "Прогноз рассчитан по средней дневной стоимости в выбранном периоде.",
      value: formatMoney(forecast),
    },
  ];

  return (
    <section className="obs-page">
      <header className="obs-hero">
        <div>
          <div className="obs-eyebrow"><Zap size={15} /> ОБЗОР ЗА ПЕРИОД</div>
          <h2>Обзор AI-систем</h2>
          <p>Расходы, бизнес-результаты, качество работы и ключевые риски.</p>
        </div>
        <div className="obs-actions">
          <select value={period} onChange={(event) => setPeriod(event.target.value)}>
            <option value="7">7 дней</option>
            <option value="30">30 дней</option>
            <option value="90">90 дней</option>
            <option value="all">Весь период</option>
          </select>
          <button type="button" onClick={load} disabled={loading}>
            <RefreshCcw size={16} className={loading ? "obs-spin" : ""} />
            Обновить
          </button>
        </div>
      </header>

      {error && <div className="obs-error">{error}</div>}
      {loading && !summary ? <div className="obs-loading">Загрузка аналитики…</div> : (
        <>
          <div className="obs-stats-grid">
            <StatCard title="Расходы за период" value={formatMoney(totalCost)} subtitle={`Прогноз: ${formatMoney(forecast)}`} icon={WalletCards} tone="violet" />
            <StatCard title="Использовано токенов" value={formatCompact(totalTokens)} subtitle={`${integer.format(n(summary?.total_requests))} LLM-запросов`} icon={Coins} tone="blue" />
            <StatCard title="Успешность запусков" value={formatPercent(totalRuns ? successfulRuns / totalRuns : 0)} subtitle={`${successfulRuns} из ${totalRuns} запусков`} icon={Target} tone="green" />
            <StatCard title="Цена полезного результата" value={costPerOutcome == null ? "—" : formatMoney(costPerOutcome)} subtitle={`${integer.format(successfulOutcomes)} полезных результатов`} icon={Gauge} tone="cyan" />
            <StatCard title="Потери на ошибках" value={formatMoney(failedCost)} subtitle={`${formatPercent(wasteRate)} всех расходов`} icon={AlertTriangle} tone="red" />
            <StatCard title="Среднее время запуска" value={averageLatency == null ? "—" : formatDuration(averageLatency)} subtitle="На один запуск" icon={Timer} tone="amber" />
          </div>

          <div className="obs-main-grid">
            <article className="obs-panel obs-panel-wide">
              <div className="obs-panel-header">
                <div>
                  <h3>Расходы по дням</h3>
                  <p>Как менялась стоимость работы AI-систем</p>
                </div>
                <strong>{formatMoney(daily.reduce((sum, item) => sum + item.cost, 0))}</strong>
              </div>
              <CostTrend points={daily} />
            </article>

            <article className="obs-panel">
              <div className="obs-panel-header">
                <div>
                  <h3>Качество запусков</h3>
                  <p>Успешные и ошибочные выполнения</p>
                </div>
              </div>
              <StatusDonut successful={successfulRuns} failed={failedRuns} />
            </article>

            <article className="obs-panel">
              <div className="obs-panel-header">
                <div>
                  <h3>Основные источники расходов</h3>
                  <p>Агенты с наибольшими расходами</p>
                </div>
                <Bot size={20} />
              </div>
              {agentRows.length ? <HorizontalBars rows={agentRows} /> : <div className="obs-empty">В runs нет идентификаторов агентов.</div>}
            </article>

            <article className="obs-panel obs-panel-wide">
              <div className="obs-panel-header">
                <div>
                  <h3>Требует внимания</h3>
                  <p>Рекомендации по затратам, качеству и эффективности</p>
                </div>
                <Activity size={20} />
              </div>
              <div className="obs-recommendations">
                {recommendations.map((item) => <Recommendation key={item.title} {...item} />)}
              </div>
            </article>
          </div>

          <article className="obs-panel obs-runs-panel">
            <div className="obs-panel-header">
              <div>
                <h3>Последние запуски</h3>
                <p>Статус, потребление ресурсов, стоимость и время выполнения</p>
              </div>
              <span className="obs-count">{filteredRuns.length} записей</span>
            </div>
            <div className="obs-table-wrap">
              <table className="obs-table">
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Продукт / агент</th>
                    <th>Статус</th>
                    <th>Токены</th>
                    <th>Стоимость</th>
                    <th>Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {[...filteredRuns]
                    .sort((a, b) => new Date(runDate(b) || 0) - new Date(runDate(a) || 0))
                    .slice(0, 12)
                    .map((run) => {
                      const deployment = deploymentById[run.deployment_id];
                      const productId = run.product_id || deployment?.product_id;
                      const status = String(run.status || "unknown").toLowerCase();
                      const good = ["success", "completed", "ok"].includes(status);
                      return (
                        <tr key={run.id || `${runDate(run)}-${Math.random()}`}>
                          <td>{formatDateTime(runDate(run))}</td>
                          <td>
                            <strong>{productById[productId] || run.product_name || "AI-продукт"}</strong>
                            <small>{run.agent_name || deployment?.service_name || deployment?.name || String(run.agent_id || "agent").slice(0, 18)}</small>
                          </td>
                          <td><span className={`obs-status ${good ? "obs-status-good" : "obs-status-bad"}`}>{good ? "Успешно" : "Ошибка"}</span></td>
                          <td>{formatCompact(runTokens(run))}</td>
                          <td>{formatMoney(runCost(run))}</td>
                          <td>{formatDuration(firstValue(run, ["latency_ms", "duration_ms"], 0))}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </article>
        </>
      )}
    </section>
  );
}
