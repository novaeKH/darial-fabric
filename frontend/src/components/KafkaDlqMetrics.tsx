import { useEffect, useMemo, useState } from "react";
import { principalFetch } from "../sessionApi";

type Metrics = {
  counts: {
    pending: number;
    replayed: number;
    resolved: number;
    total: number;
    created_last_24h: number;
  };
  replay: {
    attempted: number;
    successful: number;
    success_rate: number;
  };
  top_errors: Array<{
    error_message: string;
    count: number;
  }>;
  daily: Array<{
    day: string;
    total: number;
    pending: number;
    replayed: number;
    resolved: number;
  }>;
};

function formatDay(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  return date.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
  });
}

export default function KafkaDlqMetrics() {
  const [data, setData] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);

    try {
      const response = await principalFetch(
        "/api/kafka/dlq/metrics/summary",
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      setData((await response.json()) as Metrics);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось загрузить метрики DLQ",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const maxDaily = useMemo(() => {
    if (!data?.daily.length) return 1;
    return Math.max(
      1,
      ...data.daily.map((point) => point.total),
    );
  }, [data]);

  if (loading) {
    return (
      <div className="dlq-metrics-loading">
        Загрузка метрик Kafka DLQ…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="dlq-error">
        Метрики DLQ недоступны: {error ?? "нет данных"}
      </div>
    );
  }

  const successPercent = Math.round(
    data.replay.success_rate * 100,
  );

  return (
    <div className="dlq-metrics">
      <div className="dlq-metric-cards">
        <article className="dlq-metric-card">
          <span>Ожидают обработки</span>
          <strong>{data.counts.pending}</strong>
          <small>Требуют внимания</small>
        </article>

        <article className="dlq-metric-card">
          <span>Повторно отправлены</span>
          <strong>{data.counts.replayed}</strong>
          <small>Успешные replay</small>
        </article>

        <article className="dlq-metric-card">
          <span>Закрыты вручную</span>
          <strong>{data.counts.resolved}</strong>
          <small>Помечены решёнными</small>
        </article>

        <article className="dlq-metric-card">
          <span>Новые за 24 часа</span>
          <strong>{data.counts.created_last_24h}</strong>
          <small>Всего событий: {data.counts.total}</small>
        </article>

        <article className="dlq-metric-card">
          <span>Replay success rate</span>
          <strong>{successPercent}%</strong>
          <small>
            {data.replay.successful} из{" "}
            {data.replay.attempted} попыток
          </small>
        </article>
      </div>

      <div className="dlq-analytics-grid">
        <article className="dlq-analytics-card">
          <div className="dlq-analytics-title">
            <div>
              <h3>Динамика DLQ</h3>
              <p>Ошибочные события за последние 14 дней</p>
            </div>
            <button type="button" onClick={() => void load()}>
              Обновить
            </button>
          </div>

          <div className="dlq-bars">
            {data.daily.map((point) => (
              <div className="dlq-bar-column" key={point.day}>
                <div className="dlq-bar-track">
                  <div
                    className="dlq-bar-value"
                    style={{
                      height: `${Math.max(
                        point.total > 0 ? 8 : 0,
                        (point.total / maxDaily) * 100,
                      )}%`,
                    }}
                    title={`${point.day}: ${point.total}`}
                  />
                </div>
                <span>{formatDay(point.day)}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="dlq-analytics-card">
          <div className="dlq-analytics-title">
            <div>
              <h3>Частые причины</h3>
              <p>Основные ошибки Kafka pipeline</p>
            </div>
          </div>

          <div className="dlq-error-list">
            {data.top_errors.length === 0 ? (
              <div className="dlq-empty-details">
                Ошибок пока нет.
              </div>
            ) : (
              data.top_errors.map((item, index) => (
                <div
                  className="dlq-error-item"
                  key={`${item.error_message}-${index}`}
                >
                  <div>
                    <span>{item.error_message}</span>
                    <small>{item.count} событий</small>
                  </div>
                  <strong>{item.count}</strong>
                </div>
              ))
            )}
          </div>
        </article>
      </div>
    </div>
  );
}
