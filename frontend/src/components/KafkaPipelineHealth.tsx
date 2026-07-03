import { useEffect, useMemo, useState } from "react";
import { principalFetch } from "../sessionApi";

type Signal = {
  level: "warning" | "critical" | string;
  code: string;
  message: string;
  value: number;
};

type HealthData = {
  status: "healthy" | "warning" | "critical" | "idle";
  checked_at: string;
  producer: {
    published_total: number;
    failed_total: number;
    last_published_at?: string | null;
  };
  consumer: {
    consumed_total: number;
    last_consumed_at?: string | null;
    bridge_created_total: number;
  };
  ingestion: {
    accepted: number;
    processing: number;
    retry: number;
    dead_letter: number;
  };
  dlq: {
    pending: number;
    replayed: number;
    resolved: number;
    last_event_at?: string | null;
  };
  signals: Signal[];
};

const STATUS_LABELS: Record<string, string> = {
  healthy: "Стабильно",
  warning: "Требует внимания",
  critical: "Критическое состояние",
  idle: "Нет активности",
};

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("ru-RU");
}

export default function KafkaPipelineHealth() {
  const [data, setData] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);

    try {
      const response = await principalFetch(
        "/api/kafka/health/summary",
      );

      if (!response.ok) {
        const body = await response.text();
        throw new Error(body || `HTTP ${response.status}`);
      }

      setData((await response.json()) as HealthData);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось загрузить Kafka Health",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();

    const timer = window.setInterval(() => {
      void load();
    }, 30000);

    return () => window.clearInterval(timer);
  }, []);

  const backlog = useMemo(() => {
    if (!data) return 0;
    return (
      data.ingestion.accepted +
      data.ingestion.processing +
      data.ingestion.retry
    );
  }, [data]);

  if (loading && !data) {
    return (
      <section className="kafka-health-card">
        <div className="kafka-health-loading">
          Проверка Kafka pipeline…
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="kafka-health-card kafka-health-error">
        <strong>Kafka Pipeline Health недоступен</strong>
        <span>{error ?? "Нет данных"}</span>
        <button type="button" onClick={() => void load()}>
          Повторить
        </button>
      </section>
    );
  }

  return (
    <section className={`kafka-health-card kafka-health-${data.status}`}>
      <div className="kafka-health-header">
        <div>
          <div className="kafka-health-title-row">
            <span className="kafka-health-dot" />
            <h3>Kafka Pipeline Health</h3>
            <span className="kafka-health-status">
              {STATUS_LABELS[data.status] ?? data.status}
            </span>
          </div>
          <p>
            Producer → Redpanda → Consumer → Ingestion → DLQ
          </p>
        </div>

        <button
          type="button"
          className="kafka-health-refresh"
          onClick={() => void load()}
          disabled={loading}
        >
          Обновить
        </button>
      </div>

      <div className="kafka-health-metrics">
        <article>
          <span>Опубликовано</span>
          <strong>{data.producer.published_total}</strong>
          <small>
            Последнее: {formatDate(data.producer.last_published_at)}
          </small>
        </article>

        <article>
          <span>Принято consumer</span>
          <strong>{data.consumer.consumed_total}</strong>
          <small>
            Bridge: {data.consumer.bridge_created_total}
          </small>
        </article>

        <article>
          <span>Backlog ingestion</span>
          <strong>{backlog}</strong>
          <small>
            Retry: {data.ingestion.retry}
          </small>
        </article>

        <article>
          <span>Dead letter</span>
          <strong>{data.ingestion.dead_letter}</strong>
          <small>
            Требуют разбора
          </small>
        </article>

        <article>
          <span>Pending DLQ</span>
          <strong>{data.dlq.pending}</strong>
          <small>
            Replay: {data.dlq.replayed}
          </small>
        </article>
      </div>

      {data.signals.length > 0 ? (
        <div className="kafka-health-signals">
          {data.signals.map((signal) => (
            <div
              key={signal.code}
              className={`kafka-health-signal kafka-health-signal-${signal.level}`}
            >
              <div>
                <strong>{signal.message}</strong>
                <small>{signal.code}</small>
              </div>
              <span>{signal.value}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="kafka-health-ok">
          Активных предупреждений нет.
        </div>
      )}

      <div className="kafka-health-footer">
        Проверено: {formatDate(data.checked_at)}
      </div>
    </section>
  );
}
