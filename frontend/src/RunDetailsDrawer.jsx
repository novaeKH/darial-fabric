import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDollarSign, Coins, Cpu, Database, Gauge, RefreshCcw, ShieldAlert, Target, Wrench, X, Zap } from "lucide-react";
import { getRunDetails } from "./controlCenterApi";
import "./runDetails.css";

const money = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 6 });
const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const n = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const formatMoney = (value) => `${money.format(n(value))} ₽`;
const formatNumber = (value) => integer.format(n(value));
const formatPercent = (value) => value == null ? "—" : `${(Math.abs(n(value)) <= 1 ? n(value) * 100 : n(value)).toFixed(1)}%`;
const formatDuration = (value) => value == null ? "—" : n(value) >= 1000 ? `${(n(value) / 1000).toFixed(2)} с` : `${Math.round(n(value))} мс`;
const formatDate = (value) => value ? new Date(value).toLocaleString("ru-RU") : "—";
const statusText = (value) => ({ completed: "Завершён", success: "Успешно", failed: "Ошибка", cancelled: "Отменён", running: "Выполняется", open: "Открыто" }[String(value || "").toLowerCase()] || value || "Неизвестно");

function Status({ value }) {
  const good = ["completed", "success", "ok", "active"].includes(String(value || "").toLowerCase());
  return <span className={`rd-status ${good ? "is-good" : "is-bad"}`}>{statusText(value)}</span>;
}
function MiniMetric({ icon: Icon, label, value, note }) {
  return <article className="rd-metric"><Icon size={17} /><div><span>{label}</span><strong>{value}</strong><small>{note}</small></div></article>;
}
function TokenStrip({ call }) {
  return <div className="rd-token-strip"><span><b>{formatNumber(call.input_tokens)}</b> вход</span><span><b>{formatNumber(call.output_tokens)}</b> выход</span><span><b>{formatNumber(call.cached_tokens)}</b> кэш</span><span><b>{formatNumber(call.reasoning_tokens)}</b> reasoning</span></div>;
}
function provenanceText(call) {
  const method = call?.cost_provenance?.pricing_method;
  if (method === "server_calculated") return "Рассчитано Takt по серверному тарифу";
  if (method === "reported_by_integration") return "Передано интеграцией, не верифицировано";
  if (method === "not_calculated") return "Тариф не найден";
  return "Источник расчёта не указан";
}

export default function RunDetailsDrawer({ runId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  async function load() {
    setLoading(true); setError("");
    try { setData(await getRunDetails(runId)); }
    catch (err) { setError(err?.message || "Не удалось загрузить запуск"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [runId]);
  const summary = data?.summary || {};
  const reconciliationOk = useMemo(() => Math.abs(n(summary.run_cost) - n(summary.llm_cost) - n(summary.tool_cost) - n(summary.unattributed_cost)) < 0.00001, [summary]);

  return <div className="rd-backdrop" onMouseDown={onClose}><aside className="rd-drawer" onMouseDown={(event) => event.stopPropagation()}>
    <header className="rd-header"><div><span>ТРАССИРОВКА ЗАПУСКА</span><h2>{data?.run?.workflow_name || "Run Details"}</h2>{data && <p>{data.product?.name || "Продукт"} · {data.agent?.name || "Агент"}</p>}</div><div className="rd-header-actions"><button type="button" onClick={load} disabled={loading}><RefreshCcw size={17} className={loading ? "rd-spin" : ""} /></button><button type="button" onClick={onClose}><X size={19} /></button></div></header>
    {error && <div className="rd-error">{error}</div>}{loading && !data && <div className="rd-loading">Загрузка полной трассировки…</div>}
    {data && <div className="rd-body">
      <section className="rd-overview"><div className="rd-overview-main"><Status value={data.run.status} /><div><span>Trace ID</span><code>{data.run.trace_id}</code></div><div><span>Начало</span><strong>{formatDate(data.run.started_at)}</strong></div><div><span>Длительность</span><strong>{formatDuration(data.run.latency_ms)}</strong></div><div><span>Среда</span><strong>{data.run.environment || "—"}</strong></div><div><span>Версия</span><strong>{data.deployment?.version || "—"}</strong></div></div>{data.run.error_type && <div className="rd-run-error"><AlertTriangle size={17} />{data.run.error_type}</div>}</section>
      <section className="rd-metrics"><MiniMetric icon={Coins} label="Стоимость запуска" value={formatMoney(summary.run_cost)} note={`${summary.llm_calls || 0} LLM · ${summary.tool_calls || 0} tools`} /><MiniMetric icon={Cpu} label="Всего токенов" value={formatNumber(summary.total_tokens)} note="input + output" /><MiniMetric icon={RefreshCcw} label="Повторные попытки" value={formatNumber(summary.retry_count)} note="run + вызовы" /><MiniMetric icon={Target} label="Полезный результат" value={formatNumber(summary.successful_outcome_quantity)} note={`${formatNumber(summary.time_saved_minutes)} мин сэкономлено`} /><MiniMetric icon={CircleDollarSign} label="Бизнес-ценность" value={formatMoney(summary.estimated_business_value)} note="оценочное значение" /><MiniMetric icon={Gauge} label="ROI запуска" value={formatPercent(summary.roi)} note={`эффект ${formatMoney(summary.net_effect)}`} /></section>
      <section className="rd-section"><div className="rd-section-title"><div><Cpu size={18} /><h3>LLM-вызовы</h3><em>{data.llm_calls.length}</em></div><strong>{formatMoney(summary.llm_cost)}</strong></div><div className="rd-timeline">{data.llm_calls.map((call, index) => <article className="rd-call" key={call.id}><div className="rd-index">{index + 1}</div><div className="rd-call-main"><div className="rd-call-head"><div><strong>{call.model_name || "Модель не указана"}</strong><span>{call.provider || "provider unknown"} · {statusText(call.status)}</span></div><div><strong>{formatMoney(call.estimated_cost)}</strong><span>{formatDuration(call.latency_ms)}</span></div></div><TokenStrip call={call} /><div className="rd-call-foot"><span><Database size={13} />{call.token_source || "reported"}</span><span><RefreshCcw size={13} />{formatNumber(call.retry_count)} retries</span><span className={call.cost_provenance?.pricing_method === "server_calculated" ? "is-verified" : "is-warning"}>{call.cost_provenance?.pricing_method === "server_calculated" ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}{provenanceText(call)}</span></div></div></article>)}{!data.llm_calls.length && <div className="rd-empty">LLM-вызовы не зарегистрированы.</div>}</div></section>
      <section className="rd-section"><div className="rd-section-title"><div><Wrench size={18} /><h3>Инструменты и API</h3><em>{data.tool_calls.length}</em></div><strong>{formatMoney(summary.tool_cost)}</strong></div><div className="rd-simple-list">{data.tool_calls.map((call) => <article key={call.id}><div><strong>{call.tool_name}</strong><span>{statusText(call.status)} · {formatDuration(call.latency_ms)}</span></div><div><strong>{formatMoney(call.estimated_cost)}</strong><span>{provenanceText(call)}</span></div></article>)}{!data.tool_calls.length && <div className="rd-empty">Инструменты не вызывались.</div>}</div></section>
      <section className="rd-section"><div className="rd-section-title"><div><Target size={18} /><h3>Бизнес-результаты</h3><em>{data.outcomes.length}</em></div><strong>{formatMoney(summary.estimated_business_value)}</strong></div><div className="rd-outcomes">{data.outcomes.map((outcome) => <article key={outcome.id} className={outcome.success ? "is-success" : "is-failed"}><div className="rd-outcome-icon">{outcome.success ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}</div><div><strong>{outcome.outcome_type}</strong><span>количество: {formatNumber(outcome.quantity)} · качество: {formatPercent(outcome.quality_score)}</span></div><div><strong>{formatMoney(outcome.estimated_business_value)}</strong><span>{outcome.human_accepted === false ? "отклонено человеком" : outcome.human_accepted === true ? "принято человеком" : "без проверки"}</span></div></article>)}{!data.outcomes.length && <div className="rd-empty">Бизнес-результат не зарегистрирован.</div>}</div></section>
      <section className="rd-section"><div className="rd-section-title"><div><ShieldAlert size={18} /><h3>Governance</h3><em>{data.violations.length}</em></div></div><div className="rd-violations">{data.violations.map((violation) => <article key={violation.id}><ShieldAlert size={18} /><div><strong>{violation.policy_code}</strong><span>{violation.description}</span></div><Status value={violation.severity} /></article>)}{!data.violations.length && <div className="rd-empty">Нарушений политик не обнаружено.</div>}</div></section>
      <section className="rd-reconciliation"><div className="rd-section-title"><div><Zap size={18} /><h3>Проверка экономики</h3></div><span className={reconciliationOk ? "is-ok" : "is-warning"}>{reconciliationOk ? "Баланс сходится" : "Найдена разница"}</span></div><div className="rd-reconcile-grid"><div><span>LLM</span><strong>{formatMoney(summary.llm_cost)}</strong></div><div><span>Tools</span><strong>{formatMoney(summary.tool_cost)}</strong></div><div><span>Прочее</span><strong>{formatMoney(summary.unattributed_cost)}</strong></div><div><span>Итого run</span><strong>{formatMoney(summary.run_cost)}</strong></div></div><p>Total tokens = input + output. Cached входят во входные токены, reasoning входят в выходные и отдельно повторно не суммируются. Бизнес-ценность является оценочным показателем.</p></section>
    </div>}
  </aside></div>;
}
