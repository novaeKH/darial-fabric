import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  Boxes,
  CircleAlert,
  Coins,
  Cpu,
  ExternalLink,
  RefreshCcw,
  Plus,
  X,
} from "lucide-react";
import {
  getAgentDeployments,
  getAgentSummaries,
  getAiProducts,
  getObservabilityRuns,
  getRunDetails,
} from "./controlCenterApi";
import OnboardingWizard from "./OnboardingWizard";
import "./controlCenter.css";
import RunDetailsDrawer from "./RunDetailsDrawer";

const money = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

const n = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const runCost = (run) => n(run.total_cost ?? run.estimated_cost ?? run.cost);
const isSuccess = (run) =>
  ["success", "completed", "ok"].includes(String(run.status || "").toLowerCase());
const dateValue = (run) => run.started_at || run.created_at || run.finished_at;
const formatMoney = (value) => `${money.format(n(value))} ₽`;
const formatNumber = (value) => integer.format(n(value));
const formatPercent = (value) => `${(n(value) <= 1 ? n(value) * 100 : n(value)).toFixed(1)}%`;
const formatDuration = (value) =>
  value == null ? "—" : n(value) >= 1000 ? `${(n(value) / 1000).toFixed(1)} с` : `${Math.round(n(value))} мс`;
const formatDate = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
};

function useData() {
  const [products, setProducts] = useState([]);
  const [deployments, setDeployments] = useState([]);
  const [runs, setRuns] = useState([]);
  const [agentSummaries, setAgentSummaries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [p, d, r, a] = await Promise.all([
        getAiProducts(),
        getAgentDeployments(),
        getObservabilityRuns(500),
        getAgentSummaries(),
      ]);
      setProducts(Array.isArray(p) ? p : p?.items || []);
      setDeployments(Array.isArray(d) ? d : d?.items || []);
      setRuns(Array.isArray(r) ? r : r?.items || []);
      setAgentSummaries(Array.isArray(a) ? a : []);
    } catch (err) {
      setError(err?.message || "Ошибка загрузки данных");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);
  return { products, deployments, runs, agentSummaries, loading, error, load };
}

function Header({ eyebrow, title, text, loading, onRefresh, actionLabel, onAction }) {
  return (
    <header className="cc-header">
      <div>
        <div className="cc-eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
        <p>{text}</p>
      </div>
      <div className="cc-header-actions">
        {onAction && <button className="cc-primary-action" type="button" onClick={onAction}><Plus size={16}/>{actionLabel}</button>}
        <button type="button" onClick={onRefresh} disabled={loading}>
          <RefreshCcw size={16} className={loading ? "cc-spin" : ""} />
          Обновить
        </button>
      </div>
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
  const good = ["success", "completed", "ok", "active", "prod"].includes(
    String(value || "").toLowerCase()
  );
  return (
    <span className={`cc-badge ${good ? "cc-badge-good" : ""}`}>
      {value || "unknown"}
    </span>
  );
}

function RunDrawer({ runId, onClose }) {
  return <RunDetailsDrawer runId={runId} onClose={onClose} />;
}

export function AiProductsView() {
  const data = useData();
  const [onboardingOpen, setOnboardingOpen] = useState(false);

  const rows = useMemo(() => data.products.map((product) => {
    const agents = data.agentSummaries.filter((item) => item.product_id === product.id);
    return {
      ...product,
      agents: agents.length,
      runs: agents.reduce((sum, item) => sum + n(item.total_runs), 0),
      cost: agents.reduce((sum, item) => sum + n(item.total_cost), 0),
      tokens: agents.reduce((sum, item) => sum + n(item.total_tokens), 0),
      successful: agents.reduce((sum, item) => sum + n(item.successful_runs), 0),
    };
  }), [data.products, data.agentSummaries]);

  return (
    <section className="cc-page">
      <Header
        eyebrow="РЕЕСТР AI-СИСТЕМ"
        title="AI-продукты"
        text="Единый реестр корпоративных AI-систем, их владельцев, агентов и фактических расходов."
        loading={data.loading}
        onRefresh={data.load}
        actionLabel="Подключить AI-систему"
        onAction={() => setOnboardingOpen(true)}
      />
      {data.error && <div className="cc-error">{data.error}</div>}
      <div className="cc-metrics">
        <Metric icon={Boxes} label="AI-продукты" value={formatNumber(rows.length)} note="Зарегистрировано" />
        <Metric icon={Bot} label="Агенты" value={formatNumber(data.agentSummaries.length)} note="Активные развёртывания" />
        <Metric icon={Coins} label="Расходы" value={formatMoney(rows.reduce((s, x) => s + x.cost, 0))} note="Вся телеметрия" />
        <Metric icon={Cpu} label="Токены" value={formatNumber(rows.reduce((s, x) => s + x.tokens, 0))} note="Все модели" />
      </div>
      <div className="cc-card-grid">
        {rows.map((product) => {
          const successRate = product.runs ? product.successful / product.runs : 0;
          return (
            <article className="cc-product-card" key={product.id}>
              <div className="cc-card-top">
                <div>
                  <span className="cc-kicker">{product.business_unit || "AI-продукт"}</span>
                  <h3>{product.name || "Без названия"}</h3>
                </div>
                <Badge value={product.status || "active"} />
              </div>
              <p>{product.description || "Описание пока не заполнено."}</p>
              <div className="cc-card-stats">
                <div><span>Агенты</span><strong>{product.agents}</strong></div>
                <div><span>Запуски</span><strong>{product.runs}</strong></div>
                <div><span>Успешность</span><strong>{formatPercent(successRate)}</strong></div>
                <div><span>Стоимость</span><strong>{formatMoney(product.cost)}</strong></div>
              </div>
              <div className="cc-card-footer">
                <span>{formatNumber(product.tokens)} токенов</span>
                <span>{({ low: "Низкая", medium: "Средняя", high: "Высокая", critical: "Критическая", standard: "Стандартная" }[product.criticality] || product.criticality || "Стандартная")}</span>
              </div>
            </article>
          );
        })}
      </div>
      {onboardingOpen && (
        <OnboardingWizard
          onClose={() => setOnboardingOpen(false)}
          onComplete={() => data.load()}
        />
      )}
    </section>
  );
}

export function AiAgentsView() {
  const data = useData();

  return (
    <section className="cc-page">
      <Header
        eyebrow="РЕЕСТР АГЕНТОВ"
        title="Агенты"
        text="Версии, окружения, модели, токены, расходы и надёжность зарегистрированных агентов."
        loading={data.loading}
        onRefresh={data.load}
      />
      {data.error && <div className="cc-error">{data.error}</div>}
      <div className="cc-table-card">
        <table className="cc-table">
          <thead>
            <tr>
              <th>Агент</th><th>Продукт</th><th>Среда</th><th>Версия</th>
              <th>Запуски</th><th>Успешность</th><th>Токены</th><th>Стоимость</th><th>Модель</th><th>Активность</th>
            </tr>
          </thead>
          <tbody>
            {data.agentSummaries.map((agent) => (
              <tr key={agent.deployment_id}>
                <td><strong>{agent.agent_name}</strong><small>{agent.service_name || agent.cluster || "—"}</small></td>
                <td>{agent.product_name || "—"}</td>
                <td><Badge value={agent.environment} /></td>
                <td>{agent.version || "—"}</td>
                <td>{formatNumber(agent.total_runs)}</td>
                <td>{formatPercent(agent.success_rate)}</td>
                <td>{formatNumber(agent.total_tokens)}</td>
                <td>{formatMoney(agent.total_cost)}</td>
                <td>{agent.models?.join(", ") || "—"}</td>
                <td>{formatDate(agent.last_activity_at)}</td>
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
  const [selectedRun, setSelectedRun] = useState(null);
  const productById = useMemo(
    () => Object.fromEntries(data.products.map((x) => [x.id, x])),
    [data.products]
  );
  const agentById = useMemo(
    () => Object.fromEntries(data.agentSummaries.map((x) => [x.agent_id, x])),
    [data.agentSummaries]
  );
  const rows = [...data.runs].sort(
    (a, b) => new Date(dateValue(b) || 0) - new Date(dateValue(a) || 0)
  );

  return (
    <section className="cc-page">
      <Header
        eyebrow="ИСТОРИЯ ВЫПОЛНЕНИЯ"
        title="Запуски агентов"
        text="Откройте run, чтобы увидеть LLM-вызовы, инструменты, стоимость, outcome и нарушения."
        loading={data.loading}
        onRefresh={data.load}
      />
      {data.error && <div className="cc-error">{data.error}</div>}
      <div className="cc-metrics">
        <Metric icon={Activity} label="Запуски" value={formatNumber(rows.length)} note="Последние 500" />
        <Metric icon={Coins} label="Стоимость" value={formatMoney(rows.reduce((s, r) => s + runCost(r), 0))} note="Суммарно" />
        <Metric icon={Bot} label="Агенты" value={formatNumber(data.agentSummaries.length)} note="В реестре" />
        <Metric icon={CircleAlert} label="Ошибки" value={formatNumber(rows.filter((r) => !isSuccess(r)).length)} note="Неуспешные запуски" />
      </div>
      <div className="cc-table-card">
        <table className="cc-table cc-runs-table">
          <thead>
            <tr><th>Время</th><th>Продукт</th><th>Агент</th><th>Статус</th><th>Стоимость</th><th>Задержка</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((run) => (
              <tr key={run.id} onClick={() => setSelectedRun(run.id)}>
                <td>{formatDate(dateValue(run))}</td>
                <td>{productById[run.product_id]?.name || "—"}</td>
                <td><strong>{agentById[run.agent_id]?.agent_name || "Agent"}</strong><small>{run.workflow_name || run.trace_id}</small></td>
                <td><Badge value={run.status} /></td>
                <td>{formatMoney(runCost(run))}</td>
                <td>{formatDuration(run.latency_ms)}</td>
                <td><ExternalLink size={15} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selectedRun && <RunDrawer runId={selectedRun} onClose={() => setSelectedRun(null)} />}
    </section>
  );
}
