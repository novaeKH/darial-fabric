import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getRunDetails } from "./controlCenterApi";

const n = (v) => Number.isFinite(Number(v)) ? Number(v) : 0;
const money = (v) => `${n(v).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
const duration = (v) => v == null ? "—" : n(v) >= 1000 ? `${(n(v)/1000).toFixed(1)} с` : `${Math.round(n(v))} мс`;

function Row({ left, sub, right, note, warning=false }) {
  return <article className={`vrun-event ${warning ? "vrun-warning" : ""}`}>
    <div><strong>{left}</strong><span>{sub}</span></div>
    <div><strong>{right}</strong><span>{note}</span></div>
  </article>;
}

export default function RunViolationDrawer({ runId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getRunDetails(runId)
      .then((value) => active && setData(value))
      .catch((err) => active && setError(err?.message || "Не удалось загрузить run"));
    return () => { active = false; };
  }, [runId]);

  return <div className="vrun-backdrop" onMouseDown={onClose}>
    <aside className="vrun-drawer" onMouseDown={(e) => e.stopPropagation()}>
      <header className="vrun-head">
        <div><span>RUN TRACE</span><h3>{data?.run?.workflow_name || "Загрузка…"}</h3></div>
        <button type="button" onClick={onClose}><X size={18}/></button>
      </header>
      {error && <div className="vrun-message vrun-error">{error}</div>}
      {!data && !error && <div className="vrun-message">Загрузка трассировки…</div>}
      {data && <div className="vrun-body">
        <div className="vrun-summary">
          <div><span>Продукт</span><strong>{data.product?.name || "—"}</strong></div>
          <div><span>Агент</span><strong>{data.agent?.name || "—"}</strong></div>
          <div><span>Статус</span><strong>{data.run?.status || "—"}</strong></div>
          <div><span>Среда</span><strong>{data.run?.environment || "—"}</strong></div>
          <div><span>Стоимость</span><strong>{money(data.run?.total_cost)}</strong></div>
          <div><span>Latency</span><strong>{duration(data.run?.latency_ms)}</strong></div>
          <div className="vrun-wide"><span>Trace ID</span><strong>{data.run?.trace_id || "—"}</strong></div>
        </div>

        <section className="vrun-section"><h4>LLM-вызовы <em>{data.llm_calls?.length || 0}</em></h4>
          {(data.llm_calls || []).map((c) => <Row key={c.id} left={c.model_name || "Модель"} sub={`${c.provider || "provider"} · ${n(c.total_tokens).toLocaleString("ru-RU")} токенов`} right={money(c.estimated_cost)} note={duration(c.latency_ms)}/>)}
          {!data.llm_calls?.length && <div className="vrun-empty">LLM-вызовов нет.</div>}
        </section>

        <section className="vrun-section"><h4>Инструменты <em>{data.tool_calls?.length || 0}</em></h4>
          {(data.tool_calls || []).map((c) => <Row key={c.id} left={c.tool_name || "Tool"} sub={c.status || "—"} right={money(c.estimated_cost)} note={duration(c.latency_ms)}/>)}
          {!data.tool_calls?.length && <div className="vrun-empty">Tool calls отсутствуют.</div>}
        </section>

        <section className="vrun-section"><h4>Бизнес-результат <em>{data.outcomes?.length || 0}</em></h4>
          {(data.outcomes || []).map((o) => <Row key={o.id} left={o.outcome_type || "Outcome"} sub={o.success ? "Успешно" : "Неуспешно"} right={o.quality_score == null ? "—" : `${(n(o.quality_score)*100).toFixed(1)}%`} note="качество"/>)}
          {!data.outcomes?.length && <div className="vrun-empty">Outcome не зарегистрирован.</div>}
        </section>

        <section className="vrun-section"><h4>Нарушения <em>{data.violations?.length || 0}</em></h4>
          {(data.violations || []).map((v) => <Row key={v.id} left={v.policy_code} sub={v.description} right={v.severity} note={v.status} warning/>)}
          {!data.violations?.length && <div className="vrun-empty">Нарушений в run нет.</div>}
        </section>
      </div>}
    </aside>
  </div>;
}
