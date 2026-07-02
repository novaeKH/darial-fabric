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
  X,
} from "lucide-react";
import {
  getAgentDeployments,
  getAgentSummaries,
  getAiProducts,
  getObservabilityRuns,
  getRunDetails,
} from "./controlCenterApi";
import "./controlCenter.css";

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
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getRunDetails(runId)
      .then((value) => active && setData(value))
      .catch((err) => active && setError(err?.message || "Ошибка загрузки run"));
    return () => { active = false; };
  }, [runId]);

  return (
    <div className="cc-drawer-backdrop" onMouseDown={onClose}>
      <aside className="cc-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <div className="cc-drawer-head">
          <div>
            <span>RUN DETAILS</span>
            <h3>{data?.run?.workflow_name || "Загрузка…"}</h3>
          </div>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </div>

        {error && <div className="cc-error">{error}</div>}
        {!data && !error && <div className="cc-loading">Загрузка трассировки…</div>}

        {data && (
          <div className="cc-drawer-body">
            <div className="cc-detail-grid">
              <div><span>Продукт</span><strong>{data.product?.name || "—"}</strong></div>
              <div><span>Агент</span><strong>{data.agent?.name || "—"}</strong></div>
              <div><span>Статус</span><strong><Badge value={data.run.status} /></strong></div>
              <div><span>Среда</span><strong>{data.run.environment}</strong></div>
              <div><span>Стоимость</span><strong>{formatMoney(data.run.total_cost)}</strong></div>
              <div><span>Latency</span><strong>{formatDuration(data.run.latency_ms)}</strong></div>
              <div className="cc-detail-wide"><span>Trace ID</span><strong>{data.run.trace_id}</strong></div>
            </div>

            <section className="cc-detail-section">
              <h4>LLM-вызовы <em>{data.llm_calls.length}</em></h4>
              {data.llm_calls.map((call) => (
                <article className="cc-event" key={call.id}>
                  <div>
                    <strong>{call.model_name}</strong>
                    <span>{call.provider} · {formatNumber(call.total_tokens)} токенов</span>
                  </div>
                  <div>
                    <strong>{formatMoney(call.estimated_cost)}</strong>
                    <span>{formatDuration(call.latency_ms)}</span>
                  </div>
                </article>
              ))}
              {!data.llm_calls.length && <div className="cc-empty-row">LLM-вызовов нет.</div>}
            </section>

            <section className="cc-detail-section">
              <h4>Инструменты <em>{data.tool_calls.length}</em></h4>
              {data.tool_calls.map((call) => (
                <article className="cc-event" key={call.id}>
                  <div><strong>{call.tool_name}</strong><span>{call.status}</span></div>
                  <div><strong>{formatMoney(call.estimated_cost)}</strong><span>{formatDuration(call.latency_ms)}</span></div>
                </article>
              ))}
              {!data.tool_calls.length && <div className="cc-empty-row">Tool calls отсутствуют.</div>}
            </section>

            <section className="cc-detail-section">
              <h4>Бизнес-результат <em>{data.outcomes.length}</em></h4>
              {data.outcomes.map((outcome) => (
                <article className="cc-event" key={outcome.id}>
                  <div><strong>{outcome.outcome_type}</strong><span>{outcome.success ? "Успешно" : "Неуспешно"}</span></div>
                  <div><strong>{outcome.quality_score == null ? "—" : formatPercent(outcome.quality_score)}</strong><span>качество</span></div>
                </article>
              ))}
              {!data.outcomes.length && <div className="cc-empty-row">Outcome не зарегистрирован.</div>}
            </section>

            <section className="cc-detail-section">
              <h4>Нарушения <em>{data.violations.length}</em></h4>
              {data.violations.map((violation) => (
                <article className="cc-event cc-event-warning" key={violation.id}>
                  <div><strong>{violation.policy_code}</strong><span>{violation.description}</span></div>
                  <Badge value={violation.severity} />
                </article>
              ))}
              {!data.violations.length && <div className="cc-empty-row">Нарушений не обнаружено.</div>}
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

export function AiProductsView() {
  const data = useData();

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
        eyebrow="AI ASSET REGISTRY"
        title="AI-продукты"
        text="Единый реестр корпоративных AI-систем, их владельцев, агентов и фактических расходов."
        loading={data.loading}
        onRefresh={data.load}
      />
      {data.error && <div className="cc-error">{data.error}</div>}
      <div className="cc-metrics">
        <Metric icon={Boxes} label="AI-продукты" value={formatNumber(rows.length)} note="Зарегистрировано" />
        <Metric icon={Bot} label="Агенты" value={formatNumber(data.agentSummaries.length)} note="Активные deployments" />
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
                <span>{product.criticality || "standard"}</span>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function AiAgentsView() {
  const data = useData();

  return (
    <section className="cc-page">
      <Header
        eyebrow="AGENT REGISTRY"
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
              <th>Runs</th><th>Успешность</th><th>Токены</th><th>Стоимость</th><th>Модель</th><th>Активность</th>
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
        eyebrow="EXECUTION TRACES"
        title="Запуски агентов"
        text="Откройте run, чтобы увидеть LLM-вызовы, инструменты, стоимость, outcome и нарушения."
        loading={data.loading}
        onRefresh={data.load}
      />
      {data.error && <div className="cc-error">{data.error}</div>}
      <div className="cc-metrics">
        <Metric icon={Activity} label="Runs" value={formatNumber(rows.length)} note="Последние 500" />
        <Metric icon={Coins} label="Стоимость" value={formatMoney(rows.reduce((s, r) => s + runCost(r), 0))} note="Суммарно" />
        <Metric icon={Bot} label="Агенты" value={formatNumber(data.agentSummaries.length)} note="В реестре" />
        <Metric icon={CircleAlert} label="Ошибки" value={formatNumber(rows.filter((r) => !isSuccess(r)).length)} note="Неуспешные runs" />
      </div>
      <div className="cc-table-card">
        <table className="cc-table cc-runs-table">
          <thead>
            <tr><th>Время</th><th>Продукт</th><th>Агент</th><th>Статус</th><th>Стоимость</th><th>Latency</th><th /></tr>
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
