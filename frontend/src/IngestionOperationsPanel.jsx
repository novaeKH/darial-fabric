import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  RefreshCcw,
  RotateCcw,
  ServerCog,
} from "lucide-react";
import {
  getDeadLetterEvents,
  getOperationsSummary,
  requeueAllDeadLetters,
  requeueEvent,
} from "./ingestionOperationsApi";
import "./ingestionOperationsPanel.css";

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU");
}

export default function IngestionOperationsPanel() {
  const [summary, setSummary] = useState({});
  const [items, setItems] = useState([]);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [stats, rows] = await Promise.all([
        getOperationsSummary(),
        getDeadLetterEvents(50),
      ]);
      setSummary(stats || {});
      setItems(Array.isArray(rows) ? rows : []);
    } catch (err) {
      setError(err?.message || "Не удалось загрузить состояние worker");
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  async function requeue(id) {
    setWorking(true);
    try {
      await requeueEvent(id);
      await load();
    } catch (err) {
      setError(err?.message || "Не удалось вернуть событие в очередь");
    } finally {
      setWorking(false);
    }
  }

  async function requeueAll() {
    setWorking(true);
    try {
      await requeueAllDeadLetters();
      await load();
    } catch (err) {
      setError(err?.message || "Не удалось вернуть события в очередь");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="ops-panel">
      <div className="ops-head">
        <div>
          <span>AUTOMATIC WORKER</span>
          <h3>Фоновая обработка</h3>
          <p>
            Worker автоматически читает очередь, повторяет временные ошибки и
            изолирует неисправимые события.
          </p>
        </div>
        <button type="button" onClick={load}>
          <RefreshCcw size={15} />
          Обновить
        </button>
      </div>

      {error && <div className="ops-error">{error}</div>}

      <div className="ops-stats">
        <div><Clock3 size={17} /><span>Ожидают</span><strong>{summary.pending || 0}</strong></div>
        <div><ServerCog size={17} /><span>В обработке</span><strong>{summary.processing || 0}</strong></div>
        <div><CheckCircle2 size={17} /><span>Обработано</span><strong>{summary.processed || 0}</strong></div>
        <div><RotateCcw size={17} /><span>Повтор</span><strong>{summary.retry || 0}</strong></div>
        <div><AlertTriangle size={17} /><span>Dead letter</span><strong>{summary.dead_letter || 0}</strong></div>
      </div>

      {items.length > 0 && (
        <div className="ops-dead">
          <div className="ops-dead-head">
            <div>
              <AlertTriangle size={17} />
              <strong>Dead-letter queue</strong>
            </div>
            <button type="button" onClick={requeueAll} disabled={working}>
              <RotateCcw size={14} />
              Повторить все
            </button>
          </div>

          <div className="ops-list">
            {items.map((item) => (
              <article key={item.id}>
                <div>
                  <strong>{item.event_type}</strong>
                  <span>{item.source_name} · {item.event_id}</span>
                </div>
                <div>
                  <strong>{item.retry_count} попытки</strong>
                  <span>{item.error_message}</span>
                </div>
                <time>{formatDate(item.received_at)}</time>
                <button
                  type="button"
                  onClick={() => requeue(item.id)}
                  disabled={working}
                >
                  <RotateCcw size={14} />
                  Повторить
                </button>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
