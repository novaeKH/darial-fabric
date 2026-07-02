import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bot,
  FileText,
  Shield,
  GitBranch,
  ScrollText,
  Play,
  RefreshCcw,
  AlertTriangle,
  CheckCircle2,
  Lock,
} from "lucide-react";

import {
  getAgents,
  getFiles,
  getFilePassport,
  getAuditLogs,
  getSecurityFindings,
  getFlows,
  getComplianceReport,
  getDemoStatus,
  getDemoChecklist,
  getPermissions,
  resetDemo,
  simulatePolicy,
  runCleanScenario,
  runRiskScenario,
  runSyntheticOnce,
  getAccessGraph,
  scanFile,
  releaseFileFromQuarantine,
  grantPermission,
  revokePermission,
  getFolders,
  uploadFile,
  downloadFile,
} from "./api";

import AccessGraphView from "./AccessGraphView";
import ObservabilityDashboard from "./ObservabilityDashboard";
import { AiProductsView, AiAgentsView, AgentRunsView } from "./ControlCenterViews";

const tabs = [
  { id: "economics", label: "AI-экономика", icon: Activity },
  { id: "ai-products", label: "AI-продукты", icon: Activity },
  { id: "ai-agents", label: "Агенты", icon: Activity },
  { id: "agent-runs", label: "Запуски", icon: Activity },
  { id: "audit", label: "Аудит", icon: Activity },
];

const statusLabels = {
  approved: "Одобрен",
  completed: "Завершён",
  ok: "ОК",
  active: "Активен",
  quarantined: "Карантин",
  failed: "Ошибка",
  critical: "Критичный",
  warning: "Предупреждение",
  requires_review: "Нужна проверка",
  running: "Выполняется",
  draft: "Черновик",
  processed: "Обработан",
  reviewed: "Проверен",
  blocked: "Заблокирован",
  archived: "Архив",
  expired: "Истёк",
  deleted: "Удалён",
  revoked: "Отозван",
  success: "Успешно",
  denied: "Отказано",
  pending: "В ожидании",
  low: "Низкая",
  medium: "Средняя",
  high: "Высокая",
  info: "Информация",
};

const classificationLabels = {
  public: "Публичный",
  internal: "Внутренний",
  confidential: "Конфиденциальный",
  restricted: "Ограниченный",
};

const actionLabels = {
  read: "Чтение",
  write: "Запись",
  upload: "Загрузка",
  share: "Передача",
  grant: "Выдать доступ",
  revoke: "Отозвать",
  delete: "Удаление",
  scan: "Сканирование",
  quarantine: "Карантин",
  approve: "Одобрить",
};

function tStatus(value) {
  return statusLabels[value] || value || "-";
}

function tClassification(value) {
  return classificationLabels[value] || value || "-";
}

function tAction(value) {
  return actionLabels[value] || value || "-";
}

function Badge({ children, type = "default" }) {
  return <span className={`badge badge-${type}`}>{children}</span>;
}


function getStatusBadgeType(status) {
  if (status === "approved" || status === "completed" || status === "ok" || status === "active") return "success";
  if (status === "quarantined" || status === "failed" || status === "critical") return "danger";
  if (status === "warning" || status === "requires_review") return "warning";
  if (status === "running") return "info";
  return "default";
}

function formatApiError(err, fallback = "Действие не выполнено") {
  const detail = err?.response?.data?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (detail?.message && Array.isArray(detail?.reasons)) {
    return `${detail.message}: ${detail.reasons.join(", ")}`;
  }

  if (detail?.message) {
    return detail.message;
  }

  if (Array.isArray(detail?.reasons)) {
    return detail.reasons.join(", ");
  }

  if (detail) {
    return JSON.stringify(detail);
  }

  return err?.message || fallback;
}

function formatFileSize(bytes) {
  if (bytes === null || bytes === undefined) return "-";

  const value = Number(bytes);
  if (Number.isNaN(value)) return `${bytes} bytes`;

  if (value < 1024) return `${value} bytes`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function getFileMetadata(file) {
  return file?.metadata_json || file?.metadata || {};
}

function stripFileExtension(name = "") {
  return name.replace(/\.[^/.]+$/, "");
}

function cleanupTechnicalFileName(name = "") {
  return stripFileExtension(name)
    .replace(/^demo_/, "")
    .replace(/^processed_/, "")
    .replace(/^summary_/, "")
    .replace(/^research_/, "")
    .replace(/^qa_report_/, "")
    .replace(/_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}/g, "")
    .replace(/\b\d{4}_\d{2}_\d{2}\b/g, "")
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .trim();
}

function getDisplayFileName(file) {
  const metadata = getFileMetadata(file);
  const name = file?.name || "";

  if (metadata.display_name) return metadata.display_name;

  if (name.includes("qa_report")) return "QA-отчёт";
  if (name.includes("summary_")) return "Краткая сводка";
  if (name.includes("research_")) return "Исследовательский отчёт";
  if (name.includes("processed_")) return "Обработанный датасет";
  if (name.includes("risky_security_events") || name.includes("security_events")) return "События безопасности";
  if (name.includes("clean_server_metrics") || name.includes("server_metrics")) return "Метрики серверов";
  if (name.includes("business_events")) return "Бизнес-события";

  return cleanupTechnicalFileName(name) || name || "Файл";
}

function getFileKind(file) {
  const metadata = getFileMetadata(file);
  const name = file?.name || "";

  if (metadata.display_type) return metadata.display_type;

  if (name.includes("qa_report")) return "QA-отчёт";
  if (name.includes("summary_")) return "Автоматическая сводка";
  if (name.includes("research_")) return "Исследовательский артефакт";
  if (name.includes("processed_")) return "Обработанный файл";
  if (name.includes("security_events")) return "Датасет безопасности";
  if (name.includes("server_metrics")) return "Датасет метрик";
  if (name.includes("business_events")) return "Бизнес-датасет";

  return "Файл";
}

function getFileTechnicalName(file) {
  return file?.name || file?.id || "-";
}

function getFileSubtitle(file) {
  const parts = [getFileKind(file), tClassification(file?.classification)];

  if (file?.status) {
    parts.push(tStatus(file.status));
  }

  return parts.filter(Boolean).join(" · ");
}

function formatBoolean(value) {
  if (value === true) return "Да";
  if (value === false) return "Нет";
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function formatInfoValue(value) {
  if (typeof value === "boolean") return formatBoolean(value);
  if (Array.isArray(value)) return value.length ? `${value.length} элемент(ов)` : "Нет";
  if (value && typeof value === "object") return JSON.stringify(value);
  return value || "-";
}

function StatCard({ title, value, icon: Icon, hint }) {
  return (
    <div className="stat-card">
      <div className="stat-icon">
        <Icon size={22} />
      </div>
      <div>
        <div className="stat-title">{title}</div>
        <div className="stat-value">{value ?? 0}</div>
        {hint && <div className="stat-hint">{hint}</div>}
      </div>
    </div>
  );
}

function EmptyState({ text }) {
  return <div className="empty-state">{text}</div>;
}

function JsonBlock({ data }) {
  return <pre className="json-block">{JSON.stringify(data, null, 2)}</pre>;
}

function getRealtimeWebSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.hostname || "localhost";
  const backendPort = "8000";

  return `${protocol}//${host}:${backendPort}/api/ws/events`;
}

function tRealtimeStatus(status) {
  const labels = {
    connecting: "подключение",
    connected: "live",
    disconnected: "отключено",
    error: "ошибка",
  };

  return labels[status] || status;
}

function tRealtimeEvent(type) {
  const labels = {
    realtime_connected: "WebSocket подключён",
    file_uploaded: "Файл загружен",
    file_read: "Файл прочитан",
    file_read_denied: "Чтение запрещено",
    security_scan_finished: "Сканирование завершено",
    file_quarantined: "Файл отправлен в карантин",
    file_released: "Файл возвращён из карантина",
    flow_started: "Сценарий запущен",
    flow_finished: "Сценарий завершён",
    demo_reset: "Демо сброшено",
    clean_scenario_finished: "Clean scenario завершён",
    risk_scenario_finished: "Risk scenario завершён",
    synthetic_file_generated: "Synthetic-файл создан",
  };

  return labels[type] || type || "событие";
}

export default function App() {
  const [activeTab, setActiveTab] = useState("economics");

  const [loading, setLoading] = useState(false);
  const [lastAction, setLastAction] = useState(null);
  const [error, setError] = useState(null);
  const [realtimeStatus, setRealtimeStatus] = useState("connecting");
  const [lastRealtimeEvent, setLastRealtimeEvent] = useState(null);
  const reconnectTimeoutRef = useRef(null);
  const websocketRef = useRef(null);

  const [demoStatus, setDemoStatus] = useState(null);
  const [checklist, setChecklist] = useState(null);
  const [agents, setAgents] = useState([]);
  const [files, setFiles] = useState([]);
  const [folders, setFolders] = useState([]);
  const [selectedFileId, setSelectedFileId] = useState(null);
  const [passport, setPassport] = useState(null);
  const [audit, setAudit] = useState([]);
  const [findings, setFindings] = useState([]);
  const [flows, setFlows] = useState([]);
  const [compliance, setCompliance] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const [accessGraph, setAccessGraph] = useState({ nodes: [], edges: [] });

  async function loadAll(options = {}) {
    const silent = options.silent === true;

    if (!silent) {
      setLoading(true);
      setError(null);
    }

    try {
      const [
        statusData,
        checklistData,
        agentsData,
        filesData,
        foldersData,
        auditData,
        findingsData,
        flowsData,
        complianceData,
        permissionsData,
        accessGraphData,
      ] = await Promise.all([
        getDemoStatus(),
        getDemoChecklist(),
        getAgents(),
        getFiles(),
        getFolders(),
        getAuditLogs(),
        getSecurityFindings(),
        getFlows(),
        getComplianceReport(),
        getPermissions(),
        getAccessGraph(),
      ]);

      setDemoStatus(statusData);
      setChecklist(checklistData);
      setAgents(agentsData);
      setFiles(filesData);
      setFolders(foldersData);
      setAudit(auditData);
      setFindings(findingsData);
      setFlows(flowsData);
      setCompliance(complianceData);
      setPermissions(permissionsData);
      setAccessGraph(accessGraphData);

      if (!selectedFileId && filesData.length > 0) {
        setSelectedFileId(filesData[0].id);
      }
    } catch (err) {
      if (!silent) {
        setError(formatApiError(err, "Не удалось загрузить данные"));
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }

  async function loadPassport(fileId) {
    if (!fileId) return;

    try {
      const data = await getFilePassport(fileId);
      setPassport(data);
    } catch (err) {
      setError(formatApiError(err, "Не удалось загрузить паспорт файла"));
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    let shouldReconnect = true;

    function connectRealtime() {
      setRealtimeStatus("connecting");

      const socket = new WebSocket(getRealtimeWebSocketUrl());
      websocketRef.current = socket;

      socket.onopen = () => {
        setRealtimeStatus("connected");
      };

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          setLastRealtimeEvent(message);

          if (message.type !== "realtime_connected") {
            loadAll({ silent: true });
          }
        } catch {
          setLastRealtimeEvent({
            type: "unknown",
            message: event.data,
            created_at: new Date().toISOString(),
          });
          loadAll({ silent: true });
        }
      };

      socket.onerror = () => {
        setRealtimeStatus("error");
      };

      socket.onclose = () => {
        websocketRef.current = null;

        if (!shouldReconnect) {
          setRealtimeStatus("disconnected");
          return;
        }

        setRealtimeStatus("disconnected");
        reconnectTimeoutRef.current = window.setTimeout(connectRealtime, 3000);
      };
    }

    connectRealtime();

    return () => {
      shouldReconnect = false;

      if (reconnectTimeoutRef.current) {
        window.clearTimeout(reconnectTimeoutRef.current);
      }

      if (websocketRef.current) {
        websocketRef.current.close();
      }
    };
  }, []);

  useEffect(() => {
    if (selectedFileId) {
      loadPassport(selectedFileId);
    }
  }, [selectedFileId]);

  const counts = demoStatus?.counts || {};
  const quarantinedCount = useMemo(
    () => files.filter((f) => f.status === "quarantined").length,
    [files]
  );

  const agentNameById = useMemo(() => {
    const map = {};

    for (const agent of agents) {
      map[agent.id] = agent.name;
    }

    return map;
  }, [agents]);

  async function runAction(actionFn, label) {
    setLoading(true);
    setError(null);

    try {
      const result = await actionFn();
      setLastAction({ label, result });
      await loadAll();
    } catch (err) {
      setError(formatApiError(err, "Действие не выполнено"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo" aria-label="Darial logo">
            <Shield size={30} strokeWidth={2.2} />
          </div>
          <div>
            <div className="brand-title">Darial</div>
            <div className="brand-subtitle">Контролируемый проход для AI-агентов</div>
          </div>
        </div>

        <nav className="nav">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                className={`nav-item ${activeTab === tab.id ? "active" : ""}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon size={18} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <Badge type={checklist?.ready_for_demo ? "success" : "warning"}>
            {checklist?.ready_for_demo ? "Демо готово" : "Нужны данные"}
          </Badge>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{tabs.find((t) => t.id === activeTab)?.label}</h1>
            <p>
              Darial контролирует зашифрованные файлы агентов, политики доступа,
              аудит, безопасность и автоматические сценарии.
            </p>
          </div>

          <div className="topbar-actions">
            <div className={`realtime-indicator realtime-${realtimeStatus}`}>
              <span className="realtime-dot" />
              <div>
                <strong>{tRealtimeStatus(realtimeStatus)}</strong>
                <span>
                  {lastRealtimeEvent
                    ? `Последнее событие: ${tRealtimeEvent(lastRealtimeEvent.type)}`
                    : "Ожидание событий"}
                </span>
              </div>
            </div>

            <button className="btn btn-secondary" onClick={() => loadAll()} disabled={loading}>
              <RefreshCcw size={16} />
              Обновить
            </button>
          </div>
        </header>

        {error && (
          <div className="alert alert-danger">
            <AlertTriangle size={18} />
            <span>{typeof error === "string" ? error : JSON.stringify(error)}</span>
          </div>
        )}

        {loading && <div className="loading-line">Загрузка...</div>}

        {activeTab === "economics" && <ObservabilityDashboard />}
        {activeTab === "ai-products" && <AiProductsView />}
        {activeTab === "ai-agents" && <AiAgentsView />}
        {activeTab === "agent-runs" && <AgentRunsView />}
 {activeTab === "dashboard" && (
          <DashboardView
            counts={counts}
            agents={agents}
            files={files}
            flows={flows}
            findings={findings}
            compliance={compliance}
            quarantinedCount={quarantinedCount}
            checklist={checklist}
          />
        )}

        {activeTab === "agents" && (
          <AgentsView agents={agents} />
        )}

        {activeTab === "files" && (
          <FilesView
            files={files}
            agents={agents}
            selectedFileId={selectedFileId}
            setSelectedFileId={(id) => {
              setSelectedFileId(id);
              setActiveTab("passport");
            }}
            onChanged={loadAll}
          />
        )}

        {activeTab === "upload" && (
          <UploadView
            agents={agents}
            folders={folders}
            onUploaded={async (fileId) => {
              await loadAll();
              setSelectedFileId(fileId);
              setActiveTab("passport");
            }}
          />
        )}

        {activeTab === "policy" && (
          <PolicySimulatorView
            agents={agents}
            files={files}
          />
        )}

        {activeTab === "passport" && (
          <PassportView
            files={files}
            agents={agents}
            selectedFileId={selectedFileId}
            setSelectedFileId={setSelectedFileId}
            passport={passport}
            onChanged={loadAll}
          />
        )}

        {activeTab === "permissions" && (
          <PermissionsView
            permissions={permissions}
            agents={agents}
            files={files}
            folders={folders}
            onChanged={loadAll}
          />
        )}

        {activeTab === "security" && (
          <SecurityView
            findings={findings}
            files={files}
            agents={agents}
            openPassport={(fileId) => {
              setSelectedFileId(fileId);
              setActiveTab("passport");
            }}
            onChanged={loadAll}
          />
        )}

        {activeTab === "graph" && (
          <AccessGraphView
            graph={accessGraph}
            openPassport={(fileId) => {
              setSelectedFileId(fileId);
              setActiveTab("passport");
            }}
          />
        )}

        {activeTab === "flows" && (
          <FlowsView
            flows={flows}
            agentNameById={agentNameById}
            openPassport={(fileId) => {
              setSelectedFileId(fileId);
              setActiveTab("passport");
            }}
          />
        )}

        {activeTab === "audit" && (
          <AuditView
            audit={audit}
            agentNameById={agentNameById}
            openPassport={(fileId) => {
              setSelectedFileId(fileId);
              setActiveTab("passport");
            }}
          />
        )}

        {activeTab === "compliance" && (
          <ComplianceView compliance={compliance} />
        )}

        {activeTab === "demo" && (
          <DemoView
            loading={loading}
            lastAction={lastAction}
            runAction={runAction}
            resetDemo={resetDemo}
            runCleanScenario={runCleanScenario}
            runRiskScenario={runRiskScenario}
            runSyntheticOnce={runSyntheticOnce}
          />
        )}
      </main>
    </div>
  );
}

function DashboardView({
  counts,
  agents,
  files,
  flows,
  findings,
  compliance,
  quarantinedCount,
  checklist,
}) {
  return (
    <div className="content-grid">
      <section className="stats-grid">
        <StatCard title="Файлы" value={counts.files} icon={FileText} hint="Зашифрованные артефакты" />
        <StatCard title="Агенты" value={counts.agents} icon={Bot} hint="Независимые участники" />
        <StatCard title="События аудита" value={counts.audit_logs} icon={ScrollText} hint="Журнал операций" />
        <StatCard title="Находки безопасности" value={counts.security_findings} icon={Shield} hint="Секреты / prompt injection" />
        <StatCard title="Запуски сценариев" value={counts.flow_runs} icon={GitBranch} hint="Автоматические процессы" />
        <StatCard title="Карантин" value={quarantinedCount} icon={AlertTriangle} hint="Заблокированные файлы" />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Состояние системы</h2>
          <Badge type={checklist?.ready_for_demo ? "success" : "warning"}>
            {checklist?.ready_for_demo ? "Готово" : "Не готово"}
          </Badge>
        </div>

        <div className="posture-grid">
          {compliance?.security_posture &&
            Object.entries(compliance.security_posture).map(([key, value]) => (
              <div className="posture-item" key={key}>
                <CheckCircle2 size={18} />
                <span>{key.replaceAll("_", " ")}</span>
                <Badge type={value ? "success" : "danger"}>{String(value)}</Badge>
              </div>
            ))}
        </div>
      </section>

      <section className="panel two-column">
        <div>
          <h2>Агенты</h2>
          <div className="agent-list">
            {agents.map((agent) => (
              <div className="agent-card" key={agent.id}>
                <div>
                  <strong>{agent.name}</strong>
                  <div className="muted">{agent.role}</div>
                </div>
                <div className="agent-badges">
                  <Badge type={getStatusBadgeType(agent.risk_level)}>{agent.risk_level}</Badge>
                  <Badge>{agent.clearance_level}</Badge>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h2>Последние файлы</h2>
          <MiniFileList files={files.slice(0, 8)} />
        </div>
      </section>

      <section className="panel">
        <h2>Последние сценарии</h2>
        {flows.length === 0 ? (
          <EmptyState text="Запусков сценариев пока нет. Запустите clean scenario во вкладке Демо." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Статус</th>
                <th>Создан</th>
              </tr>
            </thead>
            <tbody>
              {flows.slice(0, 6).map((flow) => (
                <tr key={flow.id}>
                  <td>{flow.name}</td>
                  <td>
                    <Badge type={getStatusBadgeType(flow.status)}>{tStatus(flow.status)}</Badge>
                  </td>
                  <td>{formatDate(flow.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function MiniFileList({ files }) {
  if (files.length === 0) return <EmptyState text="Файлов пока нет." />;

  return (
    <div className="mini-list">
      {files.map((file) => (
        <div className="mini-row" key={file.id}>
          <div>
            <strong>{getDisplayFileName(file)}</strong>
            <div className="muted">{getFileSubtitle(file)} · {formatFileSize(file.size)}</div>
          </div>
          <Badge type={getStatusBadgeType(file.status)}>{tStatus(file.status)}</Badge>
        </div>
      ))}
    </div>
  );
}

function AgentsView({ agents }) {
  return (
    <div className="content-grid">
      <section className="stats-grid">
        <StatCard title="Агенты" value={agents.length} icon={Bot} hint="Независимые участники" />
        <StatCard
          title="Высокий риск"
          value={agents.filter((a) => a.risk_level === "high" || a.risk_level === "critical").length}
          icon={Shield}
          hint="Нужен строгий контроль"
        />
        <StatCard
          title="Автономные"
          value={agents.filter((a) => a.autonomy_level >= 4).length}
          icon={Activity}
          hint="Агенты уровня 4"
        />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Идентичности агентов</h2>
          <Badge>{agents.length} агентов</Badge>
        </div>

        {agents.length === 0 ? (
          <EmptyState text="Агенты не найдены. Выполните Reset demo." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Агент</th>
                <th>Роль</th>
                <th>Риск</th>
                <th>Автономность</th>
                <th>Уровень доступа</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr key={agent.id}>
                  <td>
                    <strong>{agent.name}</strong>
                    <div className="muted">{agent.id}</div>
                  </td>
                  <td>{agent.role}</td>
                  <td>
                    <Badge type={getStatusBadgeType(agent.risk_level)}>
                      {agent.risk_level}
                    </Badge>
                  </td>
                  <td>
                    <Badge type={agent.autonomy_level >= 4 ? "success" : "info"}>
                      уровень {agent.autonomy_level}
                    </Badge>
                  </td>
                  <td>{agent.clearance_level}</td>
                  <td>
                    <Badge type={agent.status === "active" ? "success" : "default"}>
                      {tStatus(agent.status)}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>Уровни автономности</h2>
        <div className="posture-grid">
          <div className="posture-item">
            <span>0</span>
            <span>Наблюдает</span>
            <Badge>read-only</Badge>
          </div>
          <div className="posture-item">
            <span>1</span>
            <span>Предлагает</span>
            <Badge>proposal</Badge>
          </div>
          <div className="posture-item">
            <span>2</span>
            <span>Ограниченное выполнение</span>
            <Badge type="info">limited</Badge>
          </div>
          <div className="posture-item">
            <span>3</span>
            <span>Выполнение с подтверждением</span>
            <Badge type="warning">approval</Badge>
          </div>
          <div className="posture-item">
            <span>4</span>
            <span>Полностью автономный</span>
            <Badge type="success">policy-bound</Badge>
          </div>
        </div>
      </section>
    </div>
  );
}

function PermissionsView({ permissions, agents, files, folders, onChanged }) {
  const [subjectAgentId, setSubjectAgentId] = useState("");
  const [resourceType, setResourceType] = useState("file");
  const [resourceId, setResourceId] = useState("");
  const [action, setAction] = useState("read");
  const [expiresInMinutes, setExpiresInMinutes] = useState("120");
  const [reason, setReason] = useState("Временный доступ из интерфейса");
  const [grantedByAgentId, setGrantedByAgentId] = useState("");

  const [permissionLoading, setPermissionLoading] = useState(false);
  const [permissionError, setPermissionError] = useState(null);
  const [permissionResult, setPermissionResult] = useState(null);

  const agentNameById = useMemo(() => {
    const map = {};
    for (const agent of agents) {
      map[agent.id] = agent.name;
    }
    return map;
  }, [agents]);

  const fileNameById = useMemo(() => {
    const map = {};
    for (const file of files) {
      map[file.id] = getDisplayFileName(file);
    }
    return map;
  }, [files]);

  const folderNameById = useMemo(() => {
    const map = {};
    for (const folder of folders) {
      map[folder.id] = folder.name;
    }
    return map;
  }, [folders]);

  const securityAgent = agents.find((agent) => agent.name === "security-agent");

  useEffect(() => {
    if (!grantedByAgentId && securityAgent?.id) {
      setGrantedByAgentId(securityAgent.id);
    }
  }, [securityAgent, grantedByAgentId]);

  const activePermissions = permissions.filter((p) => p.status === "active");
  const temporaryPermissions = permissions.filter((p) => p.expires_at);
  const availableResources = resourceType === "folder" ? folders : files;

  async function handleGrantPermission() {
    if (!subjectAgentId || !resourceId || !action) {
      setPermissionError("Выберите агента, ресурс и действие.");
      return;
    }

    setPermissionLoading(true);
    setPermissionError(null);

    try {
      const payload = {
        subject_agent_id: subjectAgentId,
        resource_type: resourceType,
        resource_id: resourceId,
        action,
        expires_in_minutes: expiresInMinutes ? Number(expiresInMinutes) : null,
        reason,
        granted_by_agent_id: grantedByAgentId || null,
      };

      const result = await grantPermission(payload);
      setPermissionResult(result);
      await onChanged();
    } catch (err) {
      setPermissionError(formatApiError(err, "Не удалось выдать доступ"));
    } finally {
      setPermissionLoading(false);
    }
  }

  async function handleRevokePermission(permissionId) {
    setPermissionLoading(true);
    setPermissionError(null);

    try {
      const result = await revokePermission(
        permissionId,
        grantedByAgentId || securityAgent?.id || null
      );
      setPermissionResult(result);
      await onChanged();
    } catch (err) {
      setPermissionError(formatApiError(err, "Не удалось отозвать доступ"));
    } finally {
      setPermissionLoading(false);
    }
  }

  return (
    <div className="content-grid">
      <section className="stats-grid">
        <StatCard title="Доступы" value={permissions.length} icon={Shield} hint="Все выданные права" />
        <StatCard title="Активные" value={activePermissions.length} icon={CheckCircle2} hint="Действуют сейчас" />
        <StatCard title="Временные" value={temporaryPermissions.length} icon={Lock} hint="Есть срок действия" />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Выдать доступ</h2>
          <Badge type="info">Временный доступ</Badge>
        </div>

        <p className="muted">
          Выдайте агенту временный доступ к файлу или папке. Операция будет записана в аудит.
        </p>

        <div className="permission-form-grid">
          <label>
            <span>Агент</span>
            <select
              className="select"
              value={subjectAgentId}
              onChange={(e) => setSubjectAgentId(e.target.value)}
            >
              <option value="">Выберите агента</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name} — {agent.role}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Тип ресурса</span>
            <select
              className="select"
              value={resourceType}
              onChange={(e) => {
                setResourceType(e.target.value);
                setResourceId("");
              }}
            >
              <option value="file">файл</option>
              <option value="folder">папка</option>
            </select>
          </label>

          <label>
            <span>Ресурс</span>
            <select
              className="select"
              value={resourceId}
              onChange={(e) => setResourceId(e.target.value)}
            >
              <option value="">Выберите ресурс</option>
              {availableResources.map((resource) => (
                <option key={resource.id} value={resource.id}>
                  {resourceType === "file" ? getDisplayFileName(resource) : resource.name}
                  {resourceType === "file"
                    ? ` — ${tStatus(resource.status)} — ${tClassification(resource.classification)}`
                    : ` — ${resource.id}`}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Действие</span>
            <select
              className="select"
              value={action}
              onChange={(e) => setAction(e.target.value)}
            >
              <option value="read">чтение</option>
              <option value="write">запись</option>
              <option value="share">передача</option>
              <option value="scan">сканирование</option>
              <option value="delete">удаление</option>
            </select>
          </label>

          <label>
            <span>Срок в минутах</span>
            <input
              className="input"
              value={expiresInMinutes}
              onChange={(e) => setExpiresInMinutes(e.target.value)}
              placeholder="120"
            />
          </label>

          <label>
            <span>Кем выдано</span>
            <select
              className="select"
              value={grantedByAgentId}
              onChange={(e) => setGrantedByAgentId(e.target.value)}
            >
              <option value="">система</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="full-label">
          <span>Причина</span>
          <input
            className="input"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Зачем нужен этот доступ?"
          />
        </label>

        <div className="button-row">
          <button
            className="btn"
            disabled={permissionLoading}
            onClick={handleGrantPermission}
          >
            Выдать доступ
          </button>
        </div>

        {permissionError && (
          <div className="alert alert-danger">
            <span>⚠️</span>
            <span>
              {typeof permissionError === "string"
                ? permissionError
                : JSON.stringify(permissionError)}
            </span>
          </div>
        )}

        {permissionResult && (
          <details className="action-result">
            <summary>Результат последнего действия</summary>
            <JsonBlock data={permissionResult} />
          </details>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Права доступа</h2>
          <Badge>{permissions.length} записей</Badge>
        </div>

        {permissions.length === 0 ? (
          <EmptyState text="Прав доступа пока нет. Запустите clean scenario." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Субъект</th>
                <th>Ресурс</th>
                <th>Действие</th>
                <th>Статус</th>
                <th>Истекает</th>
                <th>Причина</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {permissions.map((permission) => {
                const subjectName =
                  permission.subject_type === "agent"
                    ? agentNameById[permission.subject_id] || permission.subject_id
                    : permission.subject_id;

                const resourceName =
                  permission.resource_type === "file"
                    ? fileNameById[permission.resource_id] || permission.resource_id
                    : folderNameById[permission.resource_id] || permission.resource_id;

                return (
                  <tr key={permission.id}>
                    <td>
                      <strong>{subjectName}</strong>
                      <div className="muted">{permission.subject_type}</div>
                    </td>
                    <td>
                      <strong>{resourceName}</strong>
                      <div className="muted">{permission.resource_type}</div>
                    </td>
                    <td>
                      <Badge type="info">{tAction(permission.action)}</Badge>
                    </td>
                    <td>
                      <Badge type={permission.status === "active" ? "success" : "default"}>
                        {tStatus(permission.status)}
                      </Badge>
                    </td>
                    <td>{permission.expires_at ? formatDate(permission.expires_at) : "никогда"}</td>
                    <td>{permission.reason || "-"}</td>
                    <td>
                      {permission.status === "active" ? (
                        <button
                          className="btn btn-small btn-danger"
                          disabled={permissionLoading}
                          onClick={() => handleRevokePermission(permission.id)}
                        >
                          Отозвать
                        </button>
                      ) : (
                        <span className="muted">-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function UploadView({ agents, folders, onUploaded }) {
  const [agentId, setAgentId] = useState("");
  const [folderId, setFolderId] = useState("");
  const [classification, setClassification] = useState("internal");
  const [selectedFile, setSelectedFile] = useState(null);

  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [uploadResult, setUploadResult] = useState(null);

  const uploadAgents = agents.filter((agent) =>
    ["synthetic-data-agent", "data-agent", "research-agent", "code-agent", "qa-agent", "security-agent"].includes(agent.name)
  );

  async function handleUpload() {
    if (!agentId || !folderId || !selectedFile) {
      setUploadError("Выберите агента, папку и файл.");
      return;
    }

    setUploadLoading(true);
    setUploadError(null);

    try {
      const result = await uploadFile({
        agentId,
        folderId,
        classification,
        file: selectedFile,
      });

      setUploadResult(result);
      await onUploaded(result.id);
    } catch (err) {
      setUploadError(formatApiError(err, "Не удалось загрузить файл"));
    } finally {
      setUploadLoading(false);
    }
  }

  return (
    <div className="content-grid">
      <section className="panel">
        <div className="panel-header">
          <h2>Загрузить зашифрованный файл</h2>
          <Badge type="info">Загрузка от имени агента</Badge>
        </div>

        <p className="muted">
          Загрузите файл от имени выбранного агента. Backend зашифрует его через AES-GCM, сохранит метаданные и запишет события аудита.
        </p>

        <div className="upload-form-grid">
          <label>
            <span>Агент</span>
            <select
              className="select"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
            >
              <option value="">Выберите агента</option>
              {uploadAgents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name} — {agent.role}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Папка</span>
            <select
              className="select"
              value={folderId}
              onChange={(e) => setFolderId(e.target.value)}
            >
              <option value="">Выберите папку</option>
              {folders.map((folder) => (
                <option key={folder.id} value={folder.id}>
                  {folder.name} — {folder.id}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Классификация</span>
            <select
              className="select"
              value={classification}
              onChange={(e) => setClassification(e.target.value)}
            >
              <option value="public">публичный</option>
              <option value="internal">внутренний</option>
              <option value="confidential">конфиденциальный</option>
              <option value="restricted">ограниченный</option>
            </select>
          </label>
        </div>

        <div className="upload-dropzone">
          <input
            type="file"
            onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
          />

          {selectedFile ? (
            <div className="upload-file-preview">
              <strong>{selectedFile.name}</strong>
              <span>{formatFileSize(selectedFile.size)}</span>
            </div>
          ) : (
            <div className="muted">Выберите файл на компьютере.</div>
          )}
        </div>

        <div className="button-row">
          <button
            className="btn"
            disabled={uploadLoading}
            onClick={handleUpload}
          >
            Загрузить и зашифровать
          </button>
        </div>

        {uploadError && (
          <div className="alert alert-danger">
            <span>⚠️</span>
            <span>
              {typeof uploadError === "string"
                ? uploadError
                : JSON.stringify(uploadError)}
            </span>
          </div>
        )}

        {uploadResult && (
          <details className="action-result">
            <summary>Результат загрузки</summary>
            <JsonBlock data={uploadResult} />
          </details>
        )}
      </section>

      <section className="panel">
        <h2>Что происходит при загрузке</h2>

        <div className="upload-steps">
          <div className="upload-step">
            <strong>1. Идентичность агента</strong>
            <span>Файл загружается от имени выбранного агента.</span>
          </div>

          <div className="upload-step">
            <strong>2. Шифрование AES-GCM</strong>
            <span>Файл шифруется до сохранения в хранилище.</span>
          </div>

          <div className="upload-step">
            <strong>3. Паспорт файла</strong>
            <span>Backend создаёт метаданные, владельца и классификацию файла.</span>
          </div>

          <div className="upload-step">
            <strong>4. Журнал аудита</strong>
            <span>Записываются события upload_file и encrypt_file.</span>
          </div>
        </div>
      </section>
    </div>
  );
}

async function downloadFileFromBrowser(file, agentId) {
  const blob = await downloadFile(file.id, agentId);

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = getFileTechnicalName(file);

  document.body.appendChild(link);
  link.click();

  link.remove();
  window.URL.revokeObjectURL(url);
}

function FilesView({ files, agents, selectedFileId, setSelectedFileId, onChanged }) {
  const [downloadAgentId, setDownloadAgentId] = useState("");
  const [downloadError, setDownloadError] = useState(null);
  const [downloadLoading, setDownloadLoading] = useState(false);

  const agentNameById = useMemo(() => {
    const map = {};
    for (const agent of agents) {
      map[agent.id] = agent.name;
    }
    return map;
  }, [agents]);

  const firstOwnerAgentId = files.find((file) => file.owner_agent_id)?.owner_agent_id;
  const defaultAgent =
    agents.find((agent) => agent.id === firstOwnerAgentId) ||
    agents.find((agent) => agent.name === "synthetic-data-agent") ||
    agents[0];

  useEffect(() => {
    if (!downloadAgentId && defaultAgent?.id) {
      setDownloadAgentId(defaultAgent.id);
    }
  }, [defaultAgent, downloadAgentId]);

  async function handleDownload(file) {
    if (!downloadAgentId) {
      setDownloadError("Выберите агента для операции чтения/расшифровки.");
      return;
    }

    setDownloadLoading(true);
    setDownloadError(null);

    try {
      await downloadFileFromBrowser(file, downloadAgentId);
      await onChanged();
    } catch (err) {
      setDownloadError(formatApiError(err, "Не удалось скачать файл. Проверьте права доступа или статус файла."));
    } finally {
      setDownloadLoading(false);
    }
  }

  return (
    <div className="content-grid">
      <section className="panel">
        <div className="panel-header">
          <h2>Чтение/расшифровка от имени агента</h2>
          <Badge type="info">Проверка политики</Badge>
        </div>

        <p className="muted">
          Выберите агента, от имени которого будет выполняться чтение. Backend проверит политику доступа перед расшифровкой.
        </p>

        <div className="read-agent-row">
          <select
            className="select"
            value={downloadAgentId}
            onChange={(e) => setDownloadAgentId(e.target.value)}
          >
            <option value="">Выберите агента</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name} — {agent.role}
              </option>
            ))}
          </select>
        </div>

        {downloadError && (
          <div className="alert alert-danger">
            <AlertTriangle size={18} />
            <span>
              {typeof downloadError === "string"
                ? downloadError
                : JSON.stringify(downloadError)}
            </span>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Зашифрованные файлы</h2>
          <Badge>{files.length} файлов</Badge>
        </div>

        {files.length === 0 ? (
          <EmptyState text="Файлов пока нет. Запустите демо-сценарий." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Статус</th>
                <th>Классификация</th>
                <th>Владелец</th>
                <th>Размер</th>
                <th>Создан</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.id} className={selectedFileId === file.id ? "selected-row" : ""}>
                  <td>
                    <div className="file-title-cell">
                      <strong>{getDisplayFileName(file)}</strong>
                      <div className="muted">{getFileSubtitle(file)}</div>
                      <div className="technical-name">{getFileTechnicalName(file)}</div>
                    </div>
                  </td>
                  <td>
                    <Badge type={getStatusBadgeType(file.status)}>{tStatus(file.status)}</Badge>
                  </td>
                  <td>{getFileKind(file)}</td>
                  <td>
                    <strong>{agentNameById[file.owner_agent_id] || file.owner_agent_id}</strong>
                    <div className="muted">{file.owner_agent_id}</div>
                  </td>
                  <td>{formatFileSize(file.size)}</td>
                  <td>{formatDate(file.created_at)}</td>
                  <td>
                    <div className="table-actions">
                      <button className="btn btn-small" onClick={() => setSelectedFileId(file.id)}>
                        Паспорт
                      </button>

                      <button
                        className="btn btn-small btn-secondary"
                        disabled={downloadLoading}
                        onClick={() => handleDownload(file)}
                      >
                        Скачать
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function PassportView({ files, agents, selectedFileId, setSelectedFileId, passport, onChanged }) {
  const [readAgentId, setReadAgentId] = useState("");
  const [readError, setReadError] = useState(null);
  const [readLoading, setReadLoading] = useState(false);

  const defaultAgent =
    agents.find((agent) => agent.name === passport?.owner?.agent_name) || agents[0];

  useEffect(() => {
    if (!readAgentId && defaultAgent?.id) {
      setReadAgentId(defaultAgent.id);
    }
  }, [defaultAgent, readAgentId]);

  async function handlePassportDownload() {
    if (!passport?.file?.id || !readAgentId) {
      setReadError("Выберите файл и агента для чтения.");
      return;
    }

    const file = files.find((item) => item.id === passport.file.id);
    if (!file) {
      setReadError("Файл не найден в состоянии frontend.");
      return;
    }

    setReadLoading(true);
    setReadError(null);

    try {
      await downloadFileFromBrowser(file, readAgentId);
      await onChanged();
    } catch (err) {
      setReadError(formatApiError(err, "Не удалось скачать файл. Проверьте решение политики доступа."));
    } finally {
      setReadLoading(false);
    }
  }

  return (
    <div className="content-grid">
      <section className="panel">
        <div className="panel-header">
          <h2>Выберите файл</h2>
          <Badge>{files.length} файлов</Badge>
        </div>

        <select
          className="select"
          value={selectedFileId || ""}
          onChange={(e) => setSelectedFileId(e.target.value)}
        >
          <option value="">Выберите файл</option>
          {files.map((file) => (
            <option value={file.id} key={file.id}>
              {getDisplayFileName(file)}
            </option>
          ))}
        </select>
      </section>

      {!passport || passport.status !== "ok" ? (
        <EmptyState text="Выберите файл, чтобы увидеть паспорт." />
      ) : (
        <>
          <section className="panel passport-hero">
            <div className="passport-hero-main">
              <div>
                <h2>{getDisplayFileName(passport.file)}</h2>
                <div className="passport-subtitle">{getFileSubtitle(passport.file)}</div>
                <div className="technical-name">Техническое имя: {getFileTechnicalName(passport.file)}</div>
              </div>

              <div className="passport-badges">
                <Badge type={getStatusBadgeType(passport.file.status)}>{tStatus(passport.file.status)}</Badge>
                <Badge>{tClassification(passport.file.classification)}</Badge>
                <Badge type="success">AES-256-GCM</Badge>
              </div>
            </div>

            <div className="passport-summary-grid">
              <div className="summary-tile">
                <span>Владелец</span>
                <strong>{passport.owner?.agent_name || "-"}</strong>
              </div>
              <div className="summary-tile">
                <span>Папка</span>
                <strong>{passport.location?.folder_name || "-"}</strong>
              </div>
              <div className="summary-tile">
                <span>Размер</span>
                <strong>{formatFileSize(passport.file.size)}</strong>
              </div>
              <div className="summary-tile">
                <span>Создан</span>
                <strong>{formatDate(passport.file.created_at)}</strong>
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Чтение / расшифровка файла</h2>
              <Badge type="info">Защищено политикой</Badge>
            </div>

            <p className="muted">
              Скачивание файла запускает проверку политики доступа и событие decrypt_file в аудите.
            </p>

            <div className="passport-read-row">
              <select
                className="select"
                value={readAgentId}
                onChange={(e) => setReadAgentId(e.target.value)}
              >
                <option value="">Выберите агента</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name} — {agent.role}
                  </option>
                ))}
              </select>

              <button
                className="btn btn-secondary"
                disabled={readLoading}
                onClick={handlePassportDownload}
              >
                Скачать / расшифровать
              </button>
            </div>

            {readError && (
              <div className="alert alert-danger">
                <AlertTriangle size={18} />
                <span>{typeof readError === "string" ? readError : JSON.stringify(readError)}</span>
              </div>
            )}
          </section>

          <section className="passport-grid">
            <InfoPanel title="Владелец" data={passport.owner} />
            <InfoPanel title="Расположение" data={passport.location} />
            <InfoPanel title="Шифрование" data={passport.encryption} />
            <InfoPanel title="Метаданные" data={passport.file.metadata || {}} />
          </section>

          <section className="panel">
            <h2>Происхождение файла</h2>
            <div className="two-column">
              <div>
                <h3>Исходные файлы</h3>
                {passport.lineage.parents.length === 0 ? (
                  <EmptyState text="Исходных файлов нет." />
                ) : (
                  <MiniJsonList items={passport.lineage.parents} />
                )}
              </div>
              <div>
                <h3>Производные файлы</h3>
                {passport.lineage.children.length === 0 ? (
                  <EmptyState text="Производных файлов нет." />
                ) : (
                  <MiniJsonList items={passport.lineage.children} />
                )}
              </div>
            </div>
          </section>

          <section className="panel">
            <h2>Находки безопасности</h2>
            {passport.security_findings.length === 0 ? (
              <EmptyState text="Для этого файла находок нет." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Тип</th>
                    <th>Критичность</th>
                    <th>Описание</th>
                  </tr>
                </thead>
                <tbody>
                  {passport.security_findings.map((finding) => (
                    <tr key={finding.id}>
                      <td>{finding.finding_type}</td>
                      <td>
                        <Badge type={getStatusBadgeType(finding.severity)}>{tStatus(finding.severity)}</Badge>
                      </td>
                      <td>{finding.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="panel">
            <h2>Права доступа</h2>
            {passport.permissions.length === 0 ? (
              <EmptyState text="Прямых прав доступа к файлу нет." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Субъект</th>
                    <th>Действие</th>
                    <th>Статус</th>
                    <th>Истекает</th>
                  </tr>
                </thead>
                <tbody>
                  {passport.permissions.map((permission) => (
                    <tr key={permission.id}>
                      <td>{permission.subject_name || permission.subject_id}</td>
                      <td>{tAction(permission.action)}</td>
                      <td>
                        <Badge type={permission.status === "active" ? "success" : "default"}>
                          {tStatus(permission.status)}
                        </Badge>
                      </td>
                      <td>{permission.expires_at ? formatDate(permission.expires_at) : "никогда"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="panel">
            <h2>Последний аудит по файлу</h2>
            {passport.audit_summary.length === 0 ? (
              <EmptyState text="Событий аудита по этому файлу пока нет." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Действие</th>
                    <th>Статус</th>
                    <th>Критичность</th>
                    <th>Создан</th>
                  </tr>
                </thead>
                <tbody>
                  {passport.audit_summary.map((event) => (
                    <tr key={event.id}>
                      <td>{event.action}</td>
                      <td>{tStatus(event.status)}</td>
                      <td>
                        <Badge type={getStatusBadgeType(event.severity)}>{tStatus(event.severity)}</Badge>
                      </td>
                      <td>{formatDate(event.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function InfoPanel({ title, data }) {
  const labels = {
    agent_id: "ID агента",
    agent_name: "Имя агента",
    agent_role: "Роль",
    agent_status: "Статус",
    agent_clearance_level: "Уровень доступа",
    workspace_id: "ID пространства",
    workspace_name: "Пространство",
    folder_id: "ID папки",
    folder_name: "Папка",
    folder_chain: "Путь папок",
    object_key: "Ключ хранения",
    enabled: "Включено",
    algorithm: "Алгоритм",
    dek_per_file: "DEK на файл",
    dek_wrapping: "Защита DEK",
    encrypted_dek_stored: "DEK сохранён",
    nonce_stored: "Nonce сохранён",
    dek_nonce_stored: "DEK nonce сохранён",
    content_hash_stored: "Хэш содержимого",
    encryption: "Шифрование",
    original_filename: "Исходное имя",
    display_name: "Отображаемое имя",
    display_type: "Тип",
    scenario: "Сценарий",
    description: "Описание",
    dataset_type: "Тип датасета",
    rows_count: "Строк",
    has_anomaly: "Есть аномалии",
    anomaly_rows: "Строк с аномалиями",
    generated_at: "Сгенерирован",
    injected_security_problem: "Встроенная угроза",
    injected_problem_type: "Тип угрозы",
    generator: "Генератор",
  };

  const hiddenKeys = new Set([
    "workspace_id",
    "folder_id",
    "agent_id",
    "object_key",
    "dek_nonce",
  ]);

  const entries = Object.entries(data || {}).filter(([key]) => !hiddenKeys.has(key));

  return (
    <section className="panel info-panel">
      <h2>{title}</h2>
      {entries.length === 0 ? (
        <EmptyState text="Нет данных." />
      ) : (
        <div className="info-list">
          {entries.map(([key, value]) => (
            <div className="info-row" key={key}>
              <span>{labels[key] || key.replaceAll("_", " ")}</span>
              <strong>{formatInfoValue(value)}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function MiniJsonList({ items }) {
  return (
    <div className="mini-list">
      {items.map((item, index) => (
        <div className="mini-row" key={index}>
          <div>
            <strong>{cleanupTechnicalFileName(item.file_name || item.derived_file_name || item.source_file_name || "Файл")}</strong>
            <div className="muted">Создал: {item.created_by_agent || item.created_by_agent_name || "-"}</div>
          </div>
          <Badge>происхождение</Badge>
        </div>
      ))}
    </div>
  );
}

function PolicySimulatorView({ agents, files }) {
  const [agentId, setAgentId] = useState("");
  const [fileId, setFileId] = useState("");
  const [action, setAction] = useState("read");
  const [result, setResult] = useState(null);
  const [loadingSim, setLoadingSim] = useState(false);
  const [simError, setSimError] = useState(null);

  async function runSimulation() {
    if (!agentId || !fileId) {
      setSimError("Выберите агента и файл.");
      return;
    }

    setLoadingSim(true);
    setSimError(null);

    try {
      const data = await simulatePolicy({
        agent_id: agentId,
        file_id: fileId,
        action,
      });

      setResult(data);
    } catch (err) {
      setSimError(formatApiError(err, "Не удалось выполнить симуляцию"));
    } finally {
      setLoadingSim(false);
    }
  }

  return (
    <div className="content-grid">
      <section className="panel">
        <div className="panel-header">
          <h2>Симулятор доступа</h2>
          <Badge type="info">Объяснимый доступ</Badge>
        </div>

        <p className="muted">
          Выберите агента, действие и файл. Система объяснит, будет доступ разрешён или запрещён.
        </p>

        <div className="simulator-grid">
          <label>
            <span>Агент</span>
            <select
              className="select"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
            >
              <option value="">Выберите агента</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name} — {agent.role}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Файл</span>
            <select
              className="select"
              value={fileId}
              onChange={(e) => setFileId(e.target.value)}
            >
              <option value="">Выберите файл</option>
              {files.map((file) => (
                <option key={file.id} value={file.id}>
                  {getDisplayFileName(file)} — {tStatus(file.status)} — {tClassification(file.classification)}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Действие</span>
            <select
              className="select"
              value={action}
              onChange={(e) => setAction(e.target.value)}
            >
              <option value="read">чтение</option>
              <option value="write">запись</option>
              <option value="share">передача</option>
              <option value="delete">удаление</option>
              <option value="scan">сканирование</option>
            </select>
          </label>
        </div>

        <div className="button-row">
          <button className="btn" onClick={runSimulation} disabled={loadingSim}>
            Запустить симуляцию
          </button>
        </div>

        {simError && (
          <div className="alert alert-danger">
            <span>⚠️</span>
            <span>{typeof simError === "string" ? simError : JSON.stringify(simError)}</span>
          </div>
        )}
      </section>

      {result && (
        <section className="panel policy-result">
          <div className="panel-header">
            <h2>Решение</h2>
            <Badge type={result.decision === "allow" ? "success" : "danger"}>
              {result.decision === "allow" ? "РАЗРЕШЕНО" : "ЗАПРЕЩЕНО"}
            </Badge>
          </div>

          <div className="decision-grid">
            <div className="decision-card">
              <div className="decision-title">Агент</div>
              <strong>{result.agent?.name || result.agent?.id}</strong>
              <div className="muted">
                доступ: {result.agent?.clearance_level}, риск: {tStatus(result.agent?.risk_level)}, автономность: {result.agent?.autonomy_level}
              </div>
            </div>

            <div className="decision-card">
              <div className="decision-title">Файл</div>
              <strong>{cleanupTechnicalFileName(result.file?.name || result.file?.id || "Файл")}</strong>
              <div className="muted">
                статус: {tStatus(result.file?.status)}, классификация: {tClassification(result.file?.classification)}
              </div>
            </div>

            <div className="decision-card">
              <div className="decision-title">Путь доступа</div>
              <div>
                владелец: <Badge type={result.is_owner ? "success" : "default"}>{String(result.is_owner)}</Badge>
              </div>
              <div>
                доступ к файлу: <Badge type={result.has_file_permission ? "success" : "default"}>{String(result.has_file_permission)}</Badge>
              </div>
              <div>
                доступ к папке: <Badge type={result.has_folder_permission ? "success" : "default"}>{String(result.has_folder_permission)}</Badge>
              </div>
            </div>
          </div>

          <h3>Причины</h3>
          {result.reasons?.length === 0 ? (
            <div className="empty-state">Блокирующих причин нет. Доступ разрешён.</div>
          ) : (
            <div className="reason-list">
              {result.reasons.map((reason) => (
                <div className="reason-item" key={reason}>
                  <span>⛔</span>
                  <strong>{reason}</strong>
                </div>
              ))}
            </div>
          )}

          <details>
            <summary>Исходный результат политики</summary>
            <JsonBlock data={result} />
          </details>
        </section>
      )}
    </div>
  );
}

function ComplianceView({ compliance }) {
  if (!compliance) {
    return <EmptyState text="Отчёт ещё не загружен." />;
  }

  const summary = compliance.summary || {};
  const posture = compliance.security_posture || {};

  return (
    <div className="content-grid">
      <section className="stats-grid">
        <StatCard title="Всего файлов" value={summary.total_files} icon={FileText} hint="Все артефакты" />
        <StatCard title="Зашифровано" value={summary.encrypt_operations} icon={Lock} hint="События шифрования" />
        <StatCard title="Расшифровки" value={summary.decrypt_operations} icon={Lock} hint="События чтения" />
        <StatCard title="Отказы доступа" value={summary.denied_access} icon={AlertTriangle} hint="Запреты политики" />
        <StatCard title="Карантин" value={summary.quarantined_files} icon={Shield} hint="Заблокированные файлы" />
        <StatCard title="Сценарии" value={summary.flow_runs} icon={GitBranch} hint="Автоматические процессы" />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Отчёт безопасности</h2>
          <Badge type="info">{compliance.report_type}</Badge>
        </div>

        <p className="muted">
          Сформирован: {compliance.generated_at ? formatDate(compliance.generated_at) : "-"}
        </p>

        <div className="compliance-grid">
          {Object.entries(summary).map(([key, value]) => (
            <div className="compliance-item" key={key}>
              <span>{key.replaceAll("_", " ")}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Контроли безопасности</h2>

        <div className="posture-grid">
          {Object.entries(posture).map(([key, value]) => (
            <div className="posture-item" key={key}>
              <span>✅</span>
              <span>{key.replaceAll("_", " ")}</span>
              <Badge type={value ? "success" : "danger"}>{String(value)}</Badge>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Примечания</h2>

        <div className="note-list">
          {compliance.notes?.map((note) => (
            <div className="note-item" key={note}>
              <span>•</span>
              <span>{note}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Исходный отчёт</h2>
        <JsonBlock data={compliance} />
      </section>
    </div>
  );
}


function SecurityView({ findings, files, agents, openPassport, onChanged }) {
  const [selectedFileId, setSelectedFileId] = useState("");
  const [actionResult, setActionResult] = useState(null);
  const [securityLoading, setSecurityLoading] = useState(false);
  const [securityError, setSecurityError] = useState(null);

  const quarantined = files.filter((f) => f.status === "quarantined");

  const securityAgent = agents.find((agent) => agent.name === "security-agent");

  const fileNameById = useMemo(() => {
    const map = {};
    for (const file of files) {
      map[file.id] = getDisplayFileName(file);
    }
    return map;
  }, [files]);

  async function runSecurityAction(actionFn) {
    if (!selectedFileId) {
      setSecurityError("Выберите файл.");
      return;
    }

    setSecurityLoading(true);
    setSecurityError(null);

    try {
      const result = await actionFn();
      setActionResult(result);
      await onChanged();
    } catch (err) {
      setSecurityError(formatApiError(err, "Действие безопасности не выполнено"));
    } finally {
      setSecurityLoading(false);
    }
  }

  return (
    <div className="content-grid">
      <section className="stats-grid">
        <StatCard title="Находки" value={findings.length} icon={Shield} />
        <StatCard title="Файлы в карантине" value={quarantined.length} icon={AlertTriangle} />
        <StatCard
          title="Критичные"
          value={findings.filter((f) => f.severity === "critical").length}
          icon={AlertTriangle}
        />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Действия безопасности</h2>
          <Badge type="info">Центр безопасности</Badge>
        </div>

        <p className="muted">
          Выберите файл, запустите сканирование или верните файл из карантина после ручной проверки.
        </p>

        <div className="security-action-grid">
          <label>
            <span>Файл</span>
            <select
              className="select"
              value={selectedFileId}
              onChange={(e) => setSelectedFileId(e.target.value)}
            >
              <option value="">Выберите файл</option>
            {files.map((file) => (
              <option value={file.id} key={file.id}>
                {getDisplayFileName(file)} — {tStatus(file.status)} — {tClassification(file.classification)}
              </option>
            ))}
            </select>
          </label>

          <div className="security-buttons">
            <button
              className="btn"
              disabled={securityLoading}
              onClick={() =>
                runSecurityAction(() =>
                  scanFile(selectedFileId, securityAgent?.id || null)
                )
              }
            >
              Сканировать файл
            </button>

            <button
              className="btn btn-warning"
              disabled={securityLoading}
              onClick={() =>
                runSecurityAction(() =>
                  releaseFileFromQuarantine(
                    selectedFileId,
                    securityAgent?.id || null,
                    "Released by security-agent from frontend"
                  )
                )
              }
            >
              Вернуть из карантина
            </button>

            <button
              className="btn btn-secondary"
              disabled={!selectedFileId}
              onClick={() => openPassport(selectedFileId)}
            >
              Открыть паспорт
            </button>
          </div>
        </div>

        {securityError && (
          <div className="alert alert-danger">
            <span>⚠️</span>
            <span>{typeof securityError === "string" ? securityError : JSON.stringify(securityError)}</span>
          </div>
        )}

        {actionResult && (
          <details className="action-result">
            <summary>Результат последнего действия безопасности</summary>
            <JsonBlock data={actionResult} />
          </details>
        )}
      </section>

      <section className="panel">
        <h2>Находки безопасности</h2>

        {findings.length === 0 ? (
          <EmptyState text="Находок пока нет. Запустите risk scenario." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Тип</th>
                <th>Критичность</th>
                <th>Описание</th>
                <th>Файл</th>
                <th>Создан</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {findings.map((finding) => (
                <tr key={finding.id}>
                  <td>{finding.finding_type}</td>
                  <td>
                    <Badge type={getStatusBadgeType(finding.severity)}>
                      {tStatus(finding.severity)}
                    </Badge>
                  </td>
                  <td>{finding.description}</td>
                  <td>
                    <strong>{fileNameById[finding.file_id] || "неизвестный файл"}</strong>
                    <div className="muted">{finding.file_id}</div>
                  </td>
                  <td>{formatDate(finding.created_at)}</td>
                  <td>
                    <button
                      className="btn btn-small"
                      onClick={() => openPassport(finding.file_id)}
                    >
                      Открыть паспорт
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>Зона карантина</h2>

        {quarantined.length === 0 ? (
          <EmptyState text="Файлов в карантине нет." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Файл</th>
                <th>Классификация</th>
                <th>Размер</th>
                <th>Создан</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {quarantined.map((file) => (
                <tr key={file.id}>
                  <td>
                    <strong>{getDisplayFileName(file)}</strong>
                    <div className="muted">{getFileTechnicalName(file)}</div>
                  </td>
                  <td>{getFileKind(file)}</td>
                  <td>{formatFileSize(file.size)}</td>
                  <td>{formatDate(file.created_at)}</td>
                  <td>
                    <button
                      className="btn btn-small"
                      onClick={() => openPassport(file.id)}
                    >
                      Открыть паспорт
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function FlowsView({ flows, agentNameById, openPassport }) {
  function getFlowFileIds(flow) {
    const details = flow.details || {};
    const ids = [];

    for (const key of [
      "source_file_id",
      "processed_file_id",
      "research_file_id",
      "qa_file_id",
    ]) {
      if (details[key]) {
        ids.push({ label: key, fileId: details[key] });
      }
    }

    return ids;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Запуски сценариев</h2>
        <Badge>{flows.length} запусков</Badge>
      </div>

      {flows.length === 0 ? (
        <EmptyState text="Сценариев пока нет." />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Статус</th>
              <th>Запустил</th>
              <th>Артефакты</th>
              <th>Детали</th>
              <th>Создан</th>
            </tr>
          </thead>
          <tbody>
            {flows.map((flow) => {
              const artifactIds = getFlowFileIds(flow);

              return (
                <tr key={flow.id}>
                  <td>
                    <strong>{flow.name}</strong>
                    <div className="muted">{flow.id}</div>
                  </td>
                  <td>
                    <Badge type={getStatusBadgeType(flow.status)}>{tStatus(flow.status)}</Badge>
                  </td>
                  <td>
                    {flow.started_by_agent_id ? (
                      <>
                        <strong>
                          {agentNameById[flow.started_by_agent_id] ||
                            flow.started_by_agent_id}
                        </strong>
                        <div className="muted">{flow.started_by_agent_id}</div>
                      </>
                    ) : (
                      "система"
                    )}
                  </td>
                  <td>
                    {artifactIds.length === 0 ? (
                      <span className="muted">Артефактов нет</span>
                    ) : (
                      <div className="artifact-buttons">
                        {artifactIds.map((item) => (
                          <button
                            key={item.label}
                            className="btn btn-small btn-secondary"
                            onClick={() => openPassport(item.fileId)}
                          >
                            {item.label.replace("_file_id", "")}
                          </button>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>
                    <details>
                      <summary>смотреть</summary>
                      <JsonBlock data={flow.details || {}} />
                    </details>
                  </td>
                  <td>{formatDate(flow.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function AuditView({ audit, agentNameById, openPassport }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Журнал аудита</h2>
        <Badge>{audit.length} событий</Badge>
      </div>

      {audit.length === 0 ? (
        <EmptyState text="Событий аудита пока нет." />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Действие</th>
              <th>Статус</th>
              <th>Критичность</th>
              <th>Агент</th>
              <th>Ресурс</th>
              <th>Создан</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {audit.map((event) => (
              <tr key={event.id}>
                <td>{event.action}</td>
                <td>{tStatus(event.status)}</td>
                <td>
                  <Badge type={getStatusBadgeType(event.severity)}>
                    {tStatus(event.severity)}
                  </Badge>
                </td>
                <td>
                  {event.actor_agent_id ? (
                    <>
                      <strong>
                        {agentNameById[event.actor_agent_id] || event.actor_agent_id}
                      </strong>
                      <div className="muted">{event.actor_agent_id}</div>
                    </>
                  ) : (
                    "система"
                  )}
                </td>
                <td>
                  <div>{event.resource_type || "-"}</div>
                  <div className="muted">{event.resource_id || ""}</div>
                </td>
                <td>{formatDate(event.created_at)}</td>
                <td>
                  {event.resource_type === "file" && event.resource_id ? (
                    <button
                      className="btn btn-small"
                      onClick={() => openPassport(event.resource_id)}
                    >
                      Паспорт
                    </button>
                  ) : (
                    <span className="muted">-</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function DemoView({
  loading,
  lastAction,
  runAction,
  resetDemo,
  runCleanScenario,
  runRiskScenario,
  runSyntheticOnce,
}) {
  return (
    <div className="content-grid">
      <section className="panel">
        <h2>Управление демо</h2>
        <p className="muted">
          Эти действия подготавливают демонстрационный сценарий без ручных API-запросов. Перед Reset demo лучше остановить synthetic-worker, если он запущен.
        </p>

        <div className="button-row">
          <button className="btn btn-danger" disabled={loading} onClick={() => runAction(resetDemo, "Сбросить демо")}>
            Сбросить демо
          </button>

          <button className="btn btn-success" disabled={loading} onClick={() => runAction(runCleanScenario, "Запустить clean scenario")}>
            Запустить clean scenario
          </button>

          <button className="btn btn-warning" disabled={loading} onClick={() => runAction(runRiskScenario, "Запустить risk scenario")}>
            Запустить risk scenario
          </button>

          <button className="btn btn-secondary" disabled={loading} onClick={() => runAction(runSyntheticOnce, "Сгенерировать synthetic once")}>
            Сгенерировать synthetic once
          </button>
        </div>
      </section>

      <section className="panel">
        <h2>Результат последнего действия</h2>
        {!lastAction ? (
          <EmptyState text="Действий пока не было." />
        ) : (
          <>
            <div className="last-action-title">{lastAction.label}</div>
            <JsonBlock data={lastAction.result} />
          </>
        )}
      </section>
    </div>
  );
}

function formatDate(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}