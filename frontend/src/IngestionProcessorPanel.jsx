import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, Play, RefreshCcw } from "lucide-react";
import { getProcessingSummary, processTelemetry } from "./ingestionProcessorApi";
import "./ingestionProcessorPanel.css";

export default function IngestionProcessorPanel({ onProcessed }) {
  const [summary, setSummary] = useState({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function load() { try { setSummary(await getProcessingSummary()); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  async function process() {
    setBusy(true); setMessage(""); setError("");
    try {
      const r = await processTelemetry();
      setMessage(`Обработано: ${r.processed}. Ошибок: ${r.failed}. Неподдерживаемых: ${r.unsupported}.`);
      await load(); if (onProcessed) await onProcessed();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const cards = [
    [Clock3, "В очереди", summary.accepted || 0],
    [CheckCircle2, "Обработано", summary.processed || 0],
    [AlertCircle, "Ошибки", summary.failed || 0],
    [AlertCircle, "Не поддержано", summary.unsupported || 0],
  ];
  return <section className="proc-panel">
    <div className="proc-head"><div><span>ОБРАБОТЧИК СОБЫТИЙ</span><h3>Обработка телеметрии</h3><p>Преобразует события в запуски, LLM-вызовы, вызовы инструментов и бизнес-результаты.</p></div>
      <div className="proc-actions"><button onClick={load}><RefreshCcw size={15}/>Обновить</button><button className="proc-primary" onClick={process} disabled={busy || !summary.accepted}><Play size={15}/>{busy ? "Обработка…" : "Обработать события"}</button></div>
    </div>
    {message && <div className="proc-success">{message}</div>}{error && <div className="proc-error">{error}</div>}
    <div className="proc-stats">{cards.map(([Icon,label,value]) => <div key={label}><Icon size={17}/><span>{label}</span><strong>{value}</strong></div>)}</div>
  </section>;
}
