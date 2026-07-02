import { useEffect, useMemo, useState } from "react";
import { Activity, Bot, Boxes, CircleAlert, Coins, RefreshCcw } from "lucide-react";
import { getAiProducts, getAgentDeployments, getObservabilityRuns } from "./controlCenterApi";
import "./controlCenter.css";

const money = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

const n = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const runCost = (run) => n(run.total_cost ?? run.estimated_cost ?? run.cost);
const runTokens = (run) =>
  n(run.total_tokens) ||
  n(run.input_tokens) + n(run.output_tokens) + n(run.cached_tokens) + n(run.reasoning_tokens);
const isSuccess = (run) => ["success", "completed", "ok"].includes(String(run.status || "").toLowerCase());
const dateValue = (run) => run.started_at || run.created_at || run.finished_at;
const formatMoney = (value) => `${money.format(n(value))} ₽`;
const formatNumber = (value) => integer.format(n(value));
const formatDate = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

function useData() {
  const [products, setProducts] = useState([]);
  const [deployments, setDeployments] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [p, d, r] = await Promise.all([
        getAiProducts(),
        getAgentDeployments(),
        getObservabilityRuns(500),
      ]);
      setProducts(Array.isArray(p) ? p : p?.items || []);
      setDeployments(Array.isArray(d) ? d : d?.items || []);
      setRuns(Array.isArray(r) ? r : r?.items || []);
    } catch (err) {
      setError(err?.message || "Ошибка загрузки данных");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);
  return { products, deployments, runs, loading, error, load };
}

function Header({ eyebrow, title, text, loading, onRefresh }) {
  return (
    <header className="cc-header">
      <div>
        <div className="cc-eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
        <p>{text}</p>
      </div>
      <button type="button" onClick={onRefresh} disabled={loading}>
        <RefreshCcw size={16} className={loading ? "cc-spin" : ""} />
        Обновить
      </button>
    </header>
  );
}

function Metric({ icon: Icon, label, value, note }) {
  return (
    <article className="cc-metric">
      <div className="cc-metric-icon"><Icon size={18} /></div>
      <div className="cc-metric-label">{label}</div>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function Badge({ value }) {
  const good = ["success", "completed", "ok", "active", "prod"].includes(String(value || "").toLowerCase());
  return <span className={`cc-badge ${good ? "cc-badge-good" : ""}`}>{value || "unknown"}</span>;
}

export function AiProductsView() {
  const data = useData();

  const rows = useMemo(() => data.products.map((product) => {
    const deps = data.deployments.filter((x) => x.product_id === product.id);
    const depIds = new Set(deps.map((x) => x.id));
    const runs = data.runs.filter((r) => r.product_id === product.id || depIds.has(r.deployment_id));
    const success = runs.filter(isSuccess).length;
    return {
      ...product,
      agents: deps.length,
      runs: runs.length,
      cost: runs.reduce((s, r) => s + runCost(r), 0),
      tokens: runs.reduce((s, r) => s + runTokens(r), 0),
      successRate: runs.length ? success / runs.length * 100 : 0,
    };
  }), [data.products, data.deployments, data.runs]);

  return (
    <section className="cc-page">
      <Header eyebrow="AI ASSET REGISTRY" title="AI-продукты"
        text="Единый реестр корпоративных AI-систем, их агентов и фактических расходов."
        loading={data.loading} onRefresh={data.load} />
      {data.error && <div className="cc-error">{data.error}</div>}
      <div className="cc-metrics">
        <Metric icon={Boxes} label="AI-продукты" value={formatNumber(rows.length)} note="Зарегистрировано" />
        <Metric icon={Bot} label="Агенты" value={formatNumber(data.deployments.length)} note="Deployments" />
        <Metric icon={Coins} label="Расходы" value={formatMoney(rows.reduce((s, x) => s + x.cost, 0))} note="Последние runs" />
        <Metric icon={Activity} label="Запуски" value={formatNumber(data.runs.length)} note="До 500 записей" />
      </div>
      <div className="cc-card-grid">
        {rows.map((product) => (
          <article className="cc-product-card" key={product.id}>
            <div className="cc-card-top">
              <div>
                <span className="cc-kicker">{product.business_unit || "AI-продукт"}</span>
                <h3>{product.name || product.title || "Без названия"}</h3>
              </div>
              <Badge value={product.status || "active"} />
            </div>
            <p>{product.description || "Описание пока не заполнено."}</p>
            <div className="cc-card-stats">
              <div><span>Агенты</span><strong>{product.agents}</strong></div>
              <div><span>Запуски</span><strong>{product.runs}</strong></div>
              <div><span>Успешность</span><strong>{product.successRate.toFixed(1)}%</strong></div>
              <div><span>Стоимость</span><strong>{formatMoney(product.cost)}</strong></div>
            </div>
            <div className="cc-card-footer">
              <span>{formatNumber(product.tokens)} токенов</span>
              <span>{product.criticality || "standard"}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function AiAgentsView() {
  const data = useData();
  const productById = useMemo(
    () => Object.fromEntries(data.products.map((x) => [x.id, x])),
    [data.products]
  );

  const rows = useMemo(() => data.deployments.map((dep) => {
    const runs = data.runs.filter((r) => r.deployment_id === dep.id || r.agent_id === dep.agent_id);
    const success = runs.filter(isSuccess).length;
    return {
      ...dep,
      runsCount: runs.length,
      cost: runs.reduce((s, r) => s + runCost(r), 0),
      tokens: runs.reduce((s, r) => s + runTokens(r), 0),
      successRate: runs.length ? success / runs.length * 100 : 0,
      lastSeen: runs.map(dateValue).filter(Boolean).sort().at(-1) || dep.last_seen_at,
    };
  }), [data.deployments, data.runs]);

  return (
    <section className="cc-page">
      <Header eyebrow="AGENT REGISTRY" title="Агенты"
        text="Версии, окружения, активность, расходы и надёжность зарегистрированных агентов."
        loading={data.loading} onRefresh={data.load} />
      {data.error && <div className="cc-error">{data.error}</div>}
      <div className="cc-table-card">
        <table className="cc-table">
          <thead>
            <tr>
              <th>Агент</th><th>Продукт</th><th>Среда</th><th>Версия</th>
              <th>Runs</th><th>Успешность</th><th>Токены</th><th>Стоимость</th><th>Активность</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td><strong>{a.name || a.service_name || a.agent_name || "Agent"}</strong><small>{a.cluster || "—"}</small></td>
                <td>{productById[a.product_id]?.name || "—"}</td>
                <td><Badge value={a.environment || "unknown"} /></td>
                <td>{a.version || "—"}</td>
                <td>{formatNumber(a.runsCount)}</td>
                <td>{a.successRate.toFixed(1)}%</td>
                <td>{formatNumber(a.tokens)}</td>
                <td>{formatMoney(a.cost)}</td>
                <td>{formatDate(a.lastSeen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function AgentRunsView() {
  const data = useData();
  const products = useMemo(() => Object.fromEntries(data.products.map((x) => [x.id, x])), [data.products]);
  const deps = useMemo(() => Object.fromEntries(data.deployments.map((x) => [x.id, x])), [data.deployments]);
  const rows = [...data.runs].sort((a, b) => new Date(dateValue(b) || 0) - new Date(dateValue(a) || 0));

  return (
    <section className="cc-page">
      <Header eyebrow="EXECUTION TRACES" title="Запуски агентов"
        text="Технический статус, стоимость, токены и задержка каждого agent run."
        loading={data.loading} onRefresh={data.load} />
      {data.error && <div className="cc-error">{data.error}</div>}
      <div className="cc-metrics">
        <Metric icon={Activity} label="Runs" value={formatNumber(rows.length)} note="Последние 500" />
        <Metric icon={Coins} label="Стоимость" value={formatMoney(rows.reduce((s, r) => s + runCost(r), 0))} note="Суммарно" />
        <Metric icon={Bot} label="Токены" value={formatNumber(rows.reduce((s, r) => s + runTokens(r), 0))} note="Input + output" />
        <Metric icon={CircleAlert} label="Ошибки" value={formatNumber(rows.filter((r) => !isSuccess(r)).length)} note="Неуспешные runs" />
      </div>
      <div className="cc-table-card">
        <table className="cc-table">
          <thead>
            <tr><th>Время</th><th>Продукт</th><th>Агент</th><th>Статус</th><th>Токены</th><th>Стоимость</th><th>Latency</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const dep = deps[r.deployment_id];
              const productId = r.product_id || dep?.product_id;
              return (
                <tr key={r.id}>
                  <td>{formatDate(dateValue(r))}</td>
                  <td>{products[productId]?.name || r.product_name || "—"}</td>
                  <td><strong>{r.agent_name || dep?.name || dep?.service_name || "Agent"}</strong><small>{r.workflow_name || r.trace_id || "—"}</small></td>
                  <td><Badge value={r.status} /></td>
                  <td>{formatNumber(runTokens(r))}</td>
                  <td>{formatMoney(runCost(r))}</td>
                  <td>{n(r.latency_ms || r.duration_ms) ? `${(n(r.latency_ms || r.duration_ms) / 1000).toFixed(1)} с` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
