import { useEffect, useState } from "react";
import { principalFetch } from "../sessionApi";

type DlqEvent = {
  dlq_id: string;
  source_topic?: string | null;
  source_partition?: number | null;
  source_offset?: number | null;
  error_message: string;
  payload_json?: Record<string, unknown> | null;
  status: string;
  replay_count: number;
  last_replayed_at?: string | null;
  created_at: string;
};

type DlqResponse = {
  items: DlqEvent[];
  total: number;
};

type Props = {
  principalId?: string | null;
};

const labels: Record<string, string> = {
  pending: "Ожидает",
  replayed: "Повторно отправлено",
  resolved: "Решено",
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("ru-RU");
}

function requestHeaders(principalId?: string | null): HeadersInit {
  const result: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (principalId) result["X-Darial-Principal"] = principalId;
  return result;
}

export default function KafkaDlqPanel({ principalId }: Props) {
  const [items, setItems] = useState<DlqEvent[]>([]);
  const [status, setStatus] = useState("pending");
  const [selected, setSelected] = useState<DlqEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const query = new URLSearchParams({ limit: "100" });
      if (status !== "all") query.set("status", status);

      const response = await principalFetch(
        `/api/kafka/dlq?${query.toString()}`,
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = (await response.json()) as DlqResponse;
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [status, principalId]);

  async function action(item: DlqEvent, name: "replay" | "resolve") {
    setBusyId(item.dlq_id);
    setError(null);
    try {
      const response = await principalFetch(
        `/api/kafka/dlq/${encodeURIComponent(item.dlq_id)}/${name}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: name === "resolve" ? "{}" : undefined,
        },
      );
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail ?? `HTTP ${response.status}`);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка действия");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="dlq-panel">
      <div className="dlq-toolbar">
        <div>
          <h2>Kafka DLQ</h2>
          <p>Ошибочные события, повторная отправка и ручное закрытие.</p>
        </div>
        <button type="button" onClick={() => void load()}>
          Обновить
        </button>
      </div>

      <div className="dlq-filters">
        {[
          ["pending", "Ожидают"],
          ["replayed", "Повторно отправлены"],
          ["resolved", "Решены"],
          ["all", "Все"],
        ].map(([value, title]) => (
          <button
            key={value}
            type="button"
            className={status === value ? "active" : ""}
            onClick={() => setStatus(value)}
          >
            {title}
          </button>
        ))}
      </div>

      {error && <div className="dlq-error">{error}</div>}

      <div className="dlq-layout">
        <div className="dlq-table-wrap">
          <table className="dlq-table">
            <thead>
              <tr>
                <th>Статус</th>
                <th>Ошибка</th>
                <th>Источник</th>
                <th>Создано</th>
                <th>Replay</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6}>Загрузка…</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={6}>Событий нет</td></tr>
              ) : items.map((item) => (
                <tr
                  key={item.dlq_id}
                  onClick={() => setSelected(item)}
                  className={
                    selected?.dlq_id === item.dlq_id
                      ? "dlq-row-selected"
                      : ""
                  }
                >
                  <td>
                    <span className={`dlq-status dlq-status-${item.status}`}>
                      {labels[item.status] ?? item.status}
                    </span>
                  </td>
                  <td>
                    <strong>{item.error_message}</strong>
                    <small>{item.dlq_id}</small>
                  </td>
                  <td>
                    {item.source_topic ?? "—"}
                    <small>
                      p{item.source_partition ?? "—"} / o
                      {item.source_offset ?? "—"}
                    </small>
                  </td>
                  <td>{formatDate(item.created_at)}</td>
                  <td>{item.replay_count}</td>
                  <td>
                    <div className="dlq-actions">
                      <button
                        type="button"
                        disabled={
                          busyId === item.dlq_id ||
                          item.status === "resolved"
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          void action(item, "replay");
                        }}
                      >
                        Replay
                      </button>
                      <button
                        type="button"
                        disabled={
                          busyId === item.dlq_id ||
                          item.status === "resolved"
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          void action(item, "resolve");
                        }}
                      >
                        Решено
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <aside className="dlq-details">
          {selected ? (
            <>
              <div className="dlq-details-header">
                <div>
                  <h3>Детали события</h3>
                  <small>{selected.dlq_id}</small>
                </div>
                <button type="button" onClick={() => setSelected(null)}>×</button>
              </div>

              <dl>
                <dt>Статус</dt>
                <dd>{labels[selected.status] ?? selected.status}</dd>
                <dt>Ошибка</dt>
                <dd>{selected.error_message}</dd>
                <dt>Topic</dt>
                <dd>{selected.source_topic ?? "—"}</dd>
                <dt>Partition / offset</dt>
                <dd>
                  {selected.source_partition ?? "—"} /{" "}
                  {selected.source_offset ?? "—"}
                </dd>
                <dt>Создано</dt>
                <dd>{formatDate(selected.created_at)}</dd>
                <dt>Последний replay</dt>
                <dd>{formatDate(selected.last_replayed_at)}</dd>
              </dl>

              <h4>Payload</h4>
              <pre>{JSON.stringify(selected.payload_json, null, 2)}</pre>
            </>
          ) : (
            <div className="dlq-empty-details">
              Выбери событие, чтобы увидеть payload и технические детали.
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
