import { useEffect, useState } from "react";
import {
  Activity,
  Cable,
  CheckCircle2,
  Clipboard,
  KeyRound,
  Plus,
  Radio,
  RefreshCcw,
  X,
} from "lucide-react";
import {
  createIngestionKey,
  createIngestionSource,
  getIngestionEvents,
  getIngestionSources,
  getIngestionSummary,
} from "./integrationsApi";
import IngestionProcessorPanel from "./IngestionProcessorPanel";
import "./integrationsView.css";

function Metric({ icon: Icon, label, value, note, tone = "violet" }) {
  return (
    <article className={`int-metric int-tone-${tone}`}>
      <div className="int-metric-icon"><Icon size={19} /></div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function SourceModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    name: "",
    source_type: "python_sdk",
    environment: "prod",
    product_id: "",
  });
  const [error, setError] = useState("");

  async function create() {
    try {
      const source = await createIngestionSource({
        ...form,
        product_id: form.product_id || null,
        metadata: {},
      });
      const key = await createIngestionKey(source.id, { name: "primary" });
      onCreated({ source, key });
      onClose();
    } catch (err) {
      setError(err?.message || "Не удалось создать источник");
    }
  }

  return (
    <div className="int-backdrop" onMouseDown={onClose}>
      <div className="int-modal" onMouseDown={(e) => e.stopPropagation()}>
        <header>
          <div><span>NEW TELEMETRY SOURCE</span><h3>Подключить AI-продукт</h3></div>
          <button onClick={onClose}><X size={18} /></button>
        </header>

        <label>Название<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Тип источника
          <select value={form.source_type} onChange={(e) => setForm({ ...form, source_type: e.target.value })}>
            <option value="python_sdk">Python SDK</option>
            <option value="http_api">HTTP API</option>
            <option value="kafka">Kafka</option>
            <option value="otlp">OpenTelemetry</option>
          </select>
        </label>
        <label>Среда
          <select value={form.environment} onChange={(e) => setForm({ ...form, environment: e.target.value })}>
            <option value="prod">prod</option>
            <option value="stage">stage</option>
            <option value="dev">dev</option>
          </select>
        </label>
        <label>Product ID, необязательно<input value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })} /></label>

        {error && <div className="int-error">{error}</div>}
        <button className="int-create" onClick={create}><Plus size={16} />Создать источник и ключ</button>
      </div>
    </div>
  );
}

function KeyModal({ data, onClose }) {
  async function copy() {
    await navigator.clipboard.writeText(data.key.api_key);
  }

  return (
    <div className="int-backdrop" onMouseDown={onClose}>
      <div className="int-modal" onMouseDown={(e) => e.stopPropagation()}>
        <header>
          <div><span>API KEY CREATED</span><h3>{data.source.name}</h3></div>
          <button onClick={onClose}><X size={18} /></button>
        </header>

        <div className="int-key-warning">
          Ключ показывается только один раз. Сохрани его в secret manager.
        </div>
        <code className="int-key">{data.key.api_key}</code>
        <button className="int-create" onClick={copy}><Clipboard size={16} />Скопировать ключ</button>

        <pre className="int-code">{`from darial_sdk import DarialClient

client = DarialClient(
    base_url="http://localhost:8000",
    api_key="${data.key.api_key}"
)

client.track_run(
    event_id="run-001",
    agent_name="legal-agent",
    trace_id="trace-001",
    payload={
        "status": "completed",
        "total_cost": 1.42,
        "latency_ms": 8200
    }
)`}</pre>
      </div>
    </div>
  );
}

export default function IntegrationsView() {
  const [summary, setSummary] = useState({});
  const [sources, setSources] = useState([]);
  const [events, setEvents] = useState([]);
  const [sourceModal, setSourceModal] = useState(false);
  const [keyData, setKeyData] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [s, src, ev] = await Promise.all([
        getIngestionSummary(),
        getIngestionSources(),
        getIngestionEvents(100),
      ]);
      setSummary(s || {});
      setSources(Array.isArray(src) ? src : []);
      setEvents(Array.isArray(ev) ? ev : []);
    } catch (err) {
      setError(err?.message || "Ошибка загрузки интеграций");
    }
  }

  useEffect(() => { load(); }, []);

  async function handleCreated(data) {
    setKeyData(data);
    await load();
  }

  return (
    <section className="int-page">
      <header className="int-hero">
        <div>
          <div className="int-eyebrow">TELEMETRY INGESTION</div>
          <h2>Интеграции</h2>
          <p>
            Подключение AI-продуктов через SDK, HTTP API, Kafka или OpenTelemetry.
            API-ключи изолированы по источникам и не хранятся в открытом виде.
          </p>
        </div>
        <div className="int-actions">
          <button onClick={() => setSourceModal(true)}><Plus size={16} />Подключить источник</button>
          <button onClick={load}><RefreshCcw size={16} />Обновить</button>
        </div>
      </header>

      {error && <div className="int-error">{error}</div>}

      <div className="int-metrics">
        <Metric icon={Cable} label="Источники" value={summary.sources || 0} note={`${summary.active_sources || 0} активных`} />
        <Metric icon={KeyRound} label="API-ключи" value={summary.active_keys || 0} note="Активные ключи" tone="blue" />
        <Metric icon={Radio} label="События" value={summary.events || 0} note="Всего принято" tone="green" />
        <Metric icon={Activity} label="За 24 часа" value={summary.events_24h || 0} note="Последняя активность" tone="amber" />
      </div>

      <IngestionProcessorPanel onProcessed={load} />

      <section className="int-panel">
        <div className="int-panel-head"><h3>Источники телеметрии</h3><span>{sources.length}</span></div>
        <div className="int-source-grid">
          {sources.map((source) => (
            <article className="int-source" key={source.id}>
              <div className="int-source-head">
                <div><strong>{source.name}</strong><span>{source.source_type}</span></div>
                <span className={`int-status int-status-${source.status}`}>{source.status}</span>
              </div>
              <div className="int-source-stats">
                <div><span>Среда</span><strong>{source.environment}</strong></div>
                <div><span>События</span><strong>{source.event_count}</strong></div>
                <div><span>Ключи</span><strong>{source.key_count}</strong></div>
              </div>
              <footer>
                <span>{source.last_seen_at ? new Date(source.last_seen_at).toLocaleString("ru-RU") : "Ещё не использовался"}</span>
                <CheckCircle2 size={15} />
              </footer>
            </article>
          ))}
          {!sources.length && <div className="int-empty">Источники пока не подключены.</div>}
        </div>
      </section>

      <section className="int-panel">
        <div className="int-panel-head"><h3>Последние события</h3><span>{events.length}</span></div>
        <div className="int-events">
          {events.map((event) => (
            <article key={event.id}>
              <div><strong>{event.event_type}</strong><span>{event.source_name}</span></div>
              <code>{event.event_id}</code>
              <span>{event.agent_name || "—"}</span>
              <time>{new Date(event.received_at).toLocaleString("ru-RU")}</time>
            </article>
          ))}
          {!events.length && <div className="int-empty">События ещё не поступали.</div>}
        </div>
      </section>

      {sourceModal && <SourceModal onClose={() => setSourceModal(false)} onCreated={handleCreated} />}
      {keyData && <KeyModal data={keyData} onClose={() => setKeyData(null)} />}
    </section>
  );
}
