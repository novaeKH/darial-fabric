import { useEffect, useMemo, useState } from "react";
import { Check, Clipboard, KeyRound, Loader2, X } from "lucide-react";
import {
  createAgent,
  createAgentDeployment,
  createAiProduct,
  createIngestionKey,
  createIngestionSource,
  createModelEndpoint,
  getTeams,
} from "./controlCenterApi";
import "./onboardingWizard.css";

const initial = {
  productName: "",
  description: "",
  teamId: "",
  businessUnit: "",
  criticality: "medium",
  agentName: "",
  agentRole: "AI assistant",
  framework: "python",
  version: "1.0.0",
  environment: "prod",
  provider: "openai",
  modelName: "gpt-4o-mini",
  hostingType: "external_api",
  currency: "RUB",
  inputPrice: "",
  outputPrice: "",
};

function Field({ label, children, hint }) {
  return <label className="ow-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export default function OnboardingWizard({ onClose, onComplete }) {
  const [teams, setTeams] = useState([]);
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    getTeams().then((items) => {
      const list = Array.isArray(items) ? items : [];
      setTeams(list);
      if (list[0]) setForm((old) => ({ ...old, teamId: old.teamId || list[0].id }));
    }).catch((err) => setError(err?.message || "Не удалось загрузить команды"));
  }, []);

  const ready = useMemo(() => (
    form.productName.trim().length >= 2 &&
    form.agentName.trim().length >= 2 &&
    form.teamId && form.modelName.trim() && form.provider.trim()
  ), [form]);

  const set = (key) => (event) => setForm((old) => ({ ...old, [key]: event.target.value }));

  async function submit() {
    if (!ready || busy) return;
    setBusy(true); setError("");
    try {
      const product = await createAiProduct({
        name: form.productName.trim(),
        description: form.description.trim() || null,
        owner_team_id: form.teamId,
        owner_user_id: null,
        business_unit: form.businessUnit.trim() || null,
        criticality: form.criticality,
      });
      const agent = await createAgent({
        name: form.agentName.trim(),
        team_id: form.teamId,
        role: form.agentRole.trim() || "AI assistant",
        risk_level: form.criticality === "critical" ? "high" : form.criticality,
        autonomy_level: 2,
        clearance_level: "internal",
      });
      const deployment = await createAgentDeployment({
        product_id: product.id,
        agent_id: agent.id,
        version: form.version.trim() || "1.0.0",
        environment: form.environment,
        service_name: form.agentName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "ai-agent",
        framework: form.framework,
      });
      const model = await createModelEndpoint({
        provider: form.provider.trim(),
        model_name: form.modelName.trim(),
        deployment_name: deployment.id,
        hosting_type: form.hostingType,
        currency: form.currency,
        input_price_per_million: Number(form.inputPrice || 0),
        output_price_per_million: Number(form.outputPrice || 0),
        cached_input_price_per_million: 0,
        reasoning_price_per_million: 0,
        gpu_hour_price: 0,
      });
      const source = await createIngestionSource({
        name: `${form.agentName.trim()} / ${form.environment}`,
        source_type: "python_sdk",
        product_id: product.id,
        environment: form.environment,
        metadata: { deployment_id: deployment.id, agent_id: agent.id, model_endpoint_id: model.id },
      });
      const key = await createIngestionKey(source.id, {
        name: `${form.environment}-primary`,
        allowed_event_types: ["agent_run", "llm_call", "tool_call", "business_outcome"],
        rate_limit_per_minute: 0,
      });
      const created = { product, agent, deployment, model, source, key };
      setResult(created);
      onComplete?.(created);
    } catch (err) {
      setError(err?.message || "Не удалось подключить AI-систему");
    } finally { setBusy(false); }
  }

  async function copy(text) { await navigator.clipboard.writeText(text); }

  const snippet = result ? `# .env\nTAKT_BASE_URL=http://localhost:8000\nTAKT_API_KEY=${result.key.api_key}\n\n# Python\nfrom darial_sdk import TaktClient\n\nclient = TaktClient.from_env()\nwith client.run(\n    workflow="live-demo",\n    agent_name="${result.agent.name}",\n    product_id="${result.product.id}",\n    environment="${result.deployment.environment}",\n) as run:\n    run.record_llm_call(\n        provider="${result.model.provider}",\n        model_name="${result.model.model_name}",\n        input_tokens=1200,\n        output_tokens=240,\n        latency_ms=1800,\n    )\n    run.record_outcome(\n        outcome_type="task_completed",\n        success=True,\n        human_accepted=True,\n        time_saved_minutes=10,\n    )` : "";

  return (
    <div className="ow-backdrop" onMouseDown={onClose}>
      <section className="ow-modal" onMouseDown={(e) => e.stopPropagation()}>
        <header className="ow-head">
          <div><span>ПОДКЛЮЧЕНИЕ AI-СИСТЕМЫ</span><h2>{result ? "Система подключена" : "Новый продукт и агент"}</h2></div>
          <button onClick={onClose} aria-label="Закрыть"><X size={20}/></button>
        </header>

        {!result ? <>
          <div className="ow-progress">
            <span className="active">1. Продукт</span><span className="active">2. Агент</span><span className="active">3. Модель</span><span className="active">4. Ключ</span>
          </div>
          <div className="ow-form-grid">
            <section><h3>AI-продукт</h3>
              <Field label="Название продукта"><input value={form.productName} onChange={set("productName")} placeholder="HR Resume Assistant" /></Field>
              <Field label="Описание"><textarea value={form.description} onChange={set("description")} placeholder="Какую бизнес-задачу решает система" /></Field>
              <Field label="Команда-владелец"><select value={form.teamId} onChange={set("teamId")}><option value="">Выберите команду</option>{teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
              <Field label="Подразделение"><input value={form.businessUnit} onChange={set("businessUnit")} placeholder="HR / Legal / Procurement" /></Field>
              <Field label="Критичность"><select value={form.criticality} onChange={set("criticality")}><option value="low">Низкая</option><option value="medium">Средняя</option><option value="high">Высокая</option><option value="critical">Критическая</option></select></Field>
            </section>
            <section><h3>Агент и deployment</h3>
              <Field label="Название агента"><input value={form.agentName} onChange={set("agentName")} placeholder="Resume Screening Agent" /></Field>
              <Field label="Назначение"><input value={form.agentRole} onChange={set("agentRole")} /></Field>
              <Field label="Framework"><select value={form.framework} onChange={set("framework")}><option value="python">Python</option><option value="langchain">LangChain</option><option value="llamaindex">LlamaIndex</option><option value="custom">Custom</option></select></Field>
              <div className="ow-row"><Field label="Версия"><input value={form.version} onChange={set("version")} /></Field><Field label="Среда"><select value={form.environment} onChange={set("environment")}><option value="dev">dev</option><option value="stage">stage</option><option value="prod">prod</option></select></Field></div>
            </section>
            <section className="ow-wide"><h3>Модель и тариф</h3>
              <div className="ow-model-grid">
                <Field label="Provider"><input value={form.provider} onChange={set("provider")} /></Field>
                <Field label="Модель"><input value={form.modelName} onChange={set("modelName")} /></Field>
                <Field label="Размещение"><select value={form.hostingType} onChange={set("hostingType")}><option value="external_api">Внешний API</option><option value="internal_api">Внутренний API</option><option value="local">Локальная модель</option></select></Field>
                <Field label="Валюта"><select value={form.currency} onChange={set("currency")}><option>RUB</option><option>USD</option></select></Field>
                <Field label="Цена входа / 1 млн токенов"><input type="number" min="0" step="0.01" value={form.inputPrice} onChange={set("inputPrice")} placeholder="0" /></Field>
                <Field label="Цена выхода / 1 млн токенов"><input type="number" min="0" step="0.01" value={form.outputPrice} onChange={set("outputPrice")} placeholder="0" /></Field>
              </div>
              <p className="ow-note">Takt использует этот тариф для серверного расчёта стоимости LLM-вызовов.</p>
            </section>
          </div>
          {error && <div className="ow-error">{error}</div>}
          <footer className="ow-footer"><button className="ow-secondary" onClick={onClose}>Отмена</button><button className="ow-primary" disabled={!ready || busy} onClick={submit}>{busy ? <Loader2 className="ow-spin" size={17}/> : <KeyRound size={17}/>}Создать и выпустить ключ</button></footer>
        </> : <>
          <div className="ow-success"><Check size={24}/><div><strong>{result.product.name}</strong><span>{result.agent.name} · {result.deployment.environment} · {result.model.model_name}</span></div></div>
          <div className="ow-result-grid">
            <div><span>Product ID</span><code>{result.product.id}</code></div>
            <div><span>Agent ID</span><code>{result.agent.id}</code></div>
            <div><span>Deployment ID</span><code>{result.deployment.id}</code></div>
          </div>
          <div className="ow-key"><div><span>Telemetry API key</span><small>Показывается только один раз</small></div><code>{result.key.api_key}</code><button onClick={() => copy(result.key.api_key)}><Clipboard size={16}/>Копировать</button></div>
          <div className="ow-snippet-head"><h3>Код подключения</h3><button onClick={() => copy(snippet)}><Clipboard size={15}/>Копировать код</button></div>
          <pre className="ow-snippet">{snippet}</pre>
          <footer className="ow-footer"><button className="ow-primary" onClick={onClose}>Готово</button></footer>
        </>}
      </section>
    </div>
  );
}
