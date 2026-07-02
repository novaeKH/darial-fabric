import { memo, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const DEFAULT_GRAPH = {
  nodes: [],
  edges: [],
};

const STRUCTURE_EDGE_TYPES = new Set([
  "has_agent",
  "owns_workspace",
  "contains_folder",
  "contains_file",
  "owns_file",
]);

const PERMISSION_EDGE_TYPES = new Set([
  "has_permission",
  "grants_access_to",
]);

const LINEAGE_EDGE_TYPES = new Set([
  "derived_from",
]);

const RISKY_STATUSES = new Set([
  "quarantined",
  "blocked",
  "failed",
  "critical",
]);

const RISKY_LEVELS = new Set([
  "high",
  "critical",
]);

function Badge({ children, type = "default" }) {
  return <span className={`badge badge-${type}`}>{children}</span>;
}

function getStatusBadgeType(status) {
  if (status === "approved" || status === "completed" || status === "ok" || status === "active") {
    return "success";
  }

  if (status === "quarantined" || status === "failed" || status === "critical") {
    return "danger";
  }

  if (status === "warning" || status === "requires_review") {
    return "warning";
  }

  if (status === "running") {
    return "info";
  }

  return "default";
}

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
  blocked: "Заблокирован",
  revoked: "Отозван",
  low: "Низкий",
  medium: "Средний",
  high: "Высокий",
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
};

const typeLabels = {
  team: "Команда",
  agent: "Агент",
  workspace: "Пространство",
  folder: "Папка",
  file: "Файл",
  permission: "Доступ",
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

function tType(value) {
  return typeLabels[value] || value || "-";
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

function getDisplayNodeLabel(data) {
  const label = data?.display_label || data?.display_name || data?.label || data?.name || data?.id || "";

  if (data?.type === "permission" && data?.action && !data?.display_label) {
    return data?.status ? `${tAction(data.action)} · ${tStatus(data.status)}` : tAction(data.action);
  }

  if (data?.type !== "file") {
    return label || "-";
  }

  if (label.includes("qa_report")) return "QA-отчёт";
  if (label.includes("summary_")) return "Краткая сводка";
  if (label.includes("research_")) return "Исследовательский отчёт";
  if (label.includes("processed_")) return "Обработанный датасет";
  if (label.includes("risky_security_events") || label.includes("security_events")) return "События безопасности";
  if (label.includes("clean_server_metrics") || label.includes("server_metrics")) return "Метрики серверов";
  if (label.includes("business_events")) return "Бизнес-события";

  return cleanupTechnicalFileName(label) || label || "Файл";
}

function getFileNodeKind(data) {
  if (data?.display_type) return data.display_type;

  const label = data?.technical_name || data?.label || "";

  if (label.includes("qa_report")) return "QA-отчёт";
  if (label.includes("summary_")) return "Сводка";
  if (label.includes("research_")) return "Исследование";
  if (label.includes("processed_")) return "Обработанный файл";
  if (label.includes("security_events")) return "Датасет безопасности";
  if (label.includes("server_metrics")) return "Датасет метрик";
  if (label.includes("business_events")) return "Бизнес-датасет";

  return "Файл";
}

function GraphNode({ data }) {
  const isRisky = isRiskyNode(data);
  const nodeClass = `custom-graph-node custom-graph-node-${data.type} ${
    isRisky ? "custom-graph-node-risky" : ""
  }`;

  return (
    <div className={nodeClass} title={data.technical_name || data.label || data.id}>
      <Handle type="target" position={Position.Left} />

      <div className="graph-node-top">
        <span className="graph-node-icon">
          {isRisky ? "⚠️" : data.icon}
        </span>
        <div>
          <div className="graph-node-label">
            {formatNodeLabel(data)}
          </div>
          <div className="graph-node-type">{tType(data.type)}</div>
        </div>
      </div>

      <div className="graph-node-badges">
        {data.status && (
          <Badge type={getStatusBadgeType(data.status)}>
            {tStatus(data.status)}
          </Badge>
        )}

        {data.classification && (
          <Badge>{tClassification(data.classification)}</Badge>
        )}

        {data.risk_level && (
          <Badge type={getStatusBadgeType(data.risk_level)}>
            {tStatus(data.risk_level)}
          </Badge>
        )}

        {data.action && (
          <Badge type="info">{tAction(data.action)}</Badge>
        )}
      </div>

      <GraphNodeMeta data={data} />

      {data.type === "file" && (
        <button
          className="graph-passport-btn"
          onClick={(event) => {
            event.stopPropagation();
            data.openPassport(data.rawId);
          }}
        >
          Паспорт
        </button>
      )}

      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function GraphNodeMeta({ data }) {
  const metaItems = [];

  if (data.type === "file") {
    metaItems.push(`тип: ${getFileNodeKind(data)}`);
  }

  if (data.type === "file" && data.owner_agent_name) {
    metaItems.push(`владелец: ${data.owner_agent_name}`);
  }

  if (data.type === "file" && data.findings_count > 0) {
    metaItems.push(`находки: ${data.findings_count}`);
  }

  if (data.type === "file" && data.technical_name && getDisplayNodeLabel(data) !== data.technical_name) {
    metaItems.push(`тех. имя: ${data.technical_name}`);
  }

  if (data.type === "file" && data.metadata?.source_display_name) {
    metaItems.push(`источник: ${data.metadata.source_display_name}`);
  }

  if (data.type === "permission" && data.subject_name) {
    metaItems.push(`кому: ${data.subject_name}`);
  }

  if (data.type === "permission" && data.resource_label) {
    metaItems.push(`к чему: ${getDisplayNodeLabel({ type: data.resource_type, label: data.resource_label })}`);
  }

  if (data.type === "folder" && data.parent_folder_name) {
    metaItems.push(`родитель: ${data.parent_folder_name}`);
  }

  if (metaItems.length === 0) {
    return null;
  }

  return (
    <div className="graph-node-meta">
      {metaItems.map((item) => (
        <div
          className={item.startsWith("находки:") ? "graph-node-meta-warning" : ""}
          key={item}
        >
          {item}
        </div>
      ))}
    </div>
  );
}

const nodeTypes = {
  custom: memo(GraphNode),
};

function isRiskyNode(node) {
  return (
    RISKY_STATUSES.has(node?.status) ||
    RISKY_LEVELS.has(node?.risk_level)
  );
}

function formatNodeLabel(data) {
  const maxLengthByType = {
    file: 28,
    permission: 30,
    folder: 26,
    agent: 26,
    workspace: 26,
    team: 26,
  };

  const label = getDisplayNodeLabel(data);
  const maxLength = maxLengthByType[data?.type] || 26;

  return truncateLabel(label, maxLength);
}

function getNodeIcon(type) {
  const icons = {
    team: "🏢",
    agent: "🤖",
    workspace: "🗂️",
    folder: "📁",
    file: "📄",
    permission: "🔐",
  };

  return icons[type] || "●";
}

function getNodeLayer(type) {
  const layers = {
    team: 0,
    agent: 1,
    workspace: 1,
    folder: 2,
    file: 3,
    permission: 4,
  };

  return layers[type] ?? 5;
}

function getNodeColor(type) {
  const colors = {
    team: "#2563eb",
    agent: "#7c3aed",
    workspace: "#0891b2",
    folder: "#d97706",
    file: "#16a34a",
    permission: "#dc2626",
  };

  return colors[type] || "#64748b";
}

function getEdgeLabel(type) {
  const labels = {
    has_agent: "агент",
    owns_workspace: "владеет",
    contains_folder: "содержит",
    contains_file: "содержит",
    owns_file: "владеет файлом",
    has_permission: "имеет доступ",
    grants_access_to: "разрешает",
    derived_from: "создано из",
  };

  return labels[type] || type;
}

function truncateLabel(label, maxLength = 28) {
  if (!label) return "";

  if (label.length <= maxLength) {
    return label;
  }

  return `${label.slice(0, maxLength)}…`;
}

function getRawId(nodeId) {
  if (!nodeId || !nodeId.includes(":")) {
    return nodeId;
  }

  return nodeId.split(":").slice(1).join(":");
}

function shouldShowEdge(edge, filters) {
  if (STRUCTURE_EDGE_TYPES.has(edge.type)) return filters.structure;
  if (PERMISSION_EDGE_TYPES.has(edge.type)) return filters.permissions;
  if (LINEAGE_EDGE_TYPES.has(edge.type)) return filters.lineage;
  return true;
}

function getVisibleNodeIdsFromEdges(edges) {
  const ids = new Set();

  for (const edge of edges) {
    ids.add(edge.source);
    ids.add(edge.target);
  }

  return ids;
}

function layoutNodesByLayer(nodes) {
  const groupedByLayer = {};

  for (const node of nodes) {
    const layer = getNodeLayer(node.type);
    if (!groupedByLayer[layer]) groupedByLayer[layer] = [];
    groupedByLayer[layer].push(node);
  }

  const positions = {};
  const xGap = 360;
  const yGap = 170;

  Object.entries(groupedByLayer)
    .sort(([left], [right]) => Number(left) - Number(right))
    .forEach(([layerRaw, layerNodes]) => {
      const layer = Number(layerRaw);
      const sortedNodes = [...layerNodes].sort((a, b) => {
        const typeCompare = String(a.type).localeCompare(String(b.type));
        if (typeCompare !== 0) return typeCompare;
        return String(getDisplayNodeLabel(a)).localeCompare(String(getDisplayNodeLabel(b)));
      });

      const layerHeight = (sortedNodes.length - 1) * yGap;

      sortedNodes.forEach((node, index) => {
        positions[node.id] = {
          x: layer * xGap,
          y: index * yGap - layerHeight / 2,
        };
      });
    });

  return positions;
}

function buildReactFlowGraph(graph, openPassport, filters) {
  const safeGraph = graph || DEFAULT_GRAPH;
  const rawNodes = Array.isArray(safeGraph.nodes) ? safeGraph.nodes : [];
  const rawEdges = Array.isArray(safeGraph.edges) ? safeGraph.edges : [];

  let filteredEdges = rawEdges.filter((edge) => shouldShowEdge(edge, filters));
  let visibleNodeIds = getVisibleNodeIdsFromEdges(filteredEdges);

  let filteredNodes = rawNodes.filter((node) => {
    if (filters.riskyOnly) {
      return isRiskyNode(node);
    }

    return visibleNodeIds.has(node.id) || node.type === "team";
  });

  if (filters.riskyOnly) {
    const riskyNodeIds = new Set(filteredNodes.map((node) => node.id));

    filteredEdges = filteredEdges.filter((edge) => {
      return riskyNodeIds.has(edge.source) || riskyNodeIds.has(edge.target);
    });

    visibleNodeIds = getVisibleNodeIdsFromEdges(filteredEdges);

    for (const node of filteredNodes) {
      visibleNodeIds.add(node.id);
    }

    filteredNodes = rawNodes.filter((node) => visibleNodeIds.has(node.id));
  }

  const positions = layoutNodesByLayer(filteredNodes);

  const nodes = filteredNodes.map((node) => {
    const rawId = getRawId(node.id);

    return {
      id: node.id,
      type: "custom",
      position: positions[node.id] || { x: 0, y: 0 },
      data: {
        ...node,
        rawId,
        icon: getNodeIcon(node.type),
        openPassport,
      },
    };
  });

  const visibleReactFlowNodeIds = new Set(nodes.map((node) => node.id));

  const edges = filteredEdges
    .filter((edge) => {
      return visibleReactFlowNodeIds.has(edge.source) && visibleReactFlowNodeIds.has(edge.target);
    })
    .map((edge, index) => {
      const isLineage = edge.type === "derived_from";
      const isPermission =
        edge.type === "has_permission" || edge.type === "grants_access_to";

      return {
        id: `${edge.source}-${edge.target}-${edge.type}-${index}`,
        source: edge.source,
        target: edge.target,
        label: edge.type === "grants_access_to" && edge.label ? tAction(edge.label) : edge.label || getEdgeLabel(edge.type),
        animated: isLineage || isPermission,
        type: "smoothstep",
        style: {
          stroke: isLineage ? "#16a34a" : isPermission ? "#dc2626" : "#64748b",
          strokeWidth: isLineage || isPermission ? 2.5 : 1.5,
          strokeDasharray: isPermission ? "6 6" : undefined,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 16,
          height: 16,
        },
        labelStyle: {
          fontSize: 10,
          fontWeight: 700,
          fill: "#334155",
        },
        labelBgStyle: {
          fill: "#ffffff",
          fillOpacity: 0.88,
        },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 6,
      };
    });

  return { nodes, edges };
}

function GraphLegend() {
  const items = [
    ["🏢", "Команда"],
    ["🤖", "Агент"],
    ["🗂️", "Пространство"],
    ["📁", "Папка"],
    ["📄", "Файл"],
    ["🔐", "Доступ"],
  ];

  return (
    <div className="graph-legend">
      {items.map(([icon, label]) => (
        <div className="graph-legend-item" key={label}>
          <span>{icon}</span>
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}

function GraphLineLegend() {
  return (
    <div className="graph-line-legend">
      <span>
        <i className="graph-line-sample graph-line-structure" /> Структура
      </span>
      <span>
        <i className="graph-line-sample graph-line-permission" /> Доступы
      </span>
      <span>
        <i className="graph-line-sample graph-line-lineage" /> Происхождение
      </span>
      <span>
        <i className="graph-node-sample graph-node-sample-risk" /> Риск / карантин
      </span>
    </div>
  );
}

function AccessGraphView({ graph, openPassport }) {
  const [filters, setFilters] = useState({
    structure: true,
    permissions: true,
    lineage: true,
    riskyOnly: false,
  });

  const hasGraphData = Boolean(graph?.nodes?.length);

  const { nodes, edges } = useMemo(() => {
    return buildReactFlowGraph(graph, openPassport, filters);
  }, [graph, openPassport, filters]);

  const stats = useMemo(() => {
    const counts = {};
    const safeNodes = Array.isArray(graph?.nodes) ? graph.nodes : [];

    for (const node of safeNodes) {
      counts[node.type] = (counts[node.type] || 0) + 1;
    }

    return counts;
  }, [graph]);

  function toggleFilter(key) {
    setFilters((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  return (
    <div className="content-grid">
      <section className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon">●</div>
          <div>
            <div className="stat-title">Узлы</div>
            <div className="stat-value">{nodes.length}</div>
            <div className="stat-hint">Видимые сущности</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">→</div>
          <div>
            <div className="stat-title">Связи</div>
            <div className="stat-value">{edges.length}</div>
            <div className="stat-hint">Видимые отношения</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">🤖</div>
          <div>
            <div className="stat-title">Агенты</div>
            <div className="stat-value">{stats.agent || 0}</div>
            <div className="stat-hint">Субъекты доступа</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">📄</div>
          <div>
            <div className="stat-title">Файлы</div>
            <div className="stat-value">{stats.file || 0}</div>
            <div className="stat-hint">Артефакты</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">🔐</div>
          <div>
            <div className="stat-title">Доступы</div>
            <div className="stat-value">{stats.permission || 0}</div>
            <div className="stat-hint">Выданные права</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">🧬</div>
          <div>
            <div className="stat-title">Происхождение</div>
            <div className="stat-value">
              {(graph?.edges || []).filter((e) => e.type === "derived_from").length}
            </div>
            <div className="stat-hint">Производные файлы</div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Интерактивный граф доступа</h2>
          <Badge type="info">Масштаб / перемещение / просмотр</Badge>
        </div>

        <p className="muted">
          Граф показывает команды, агентов, рабочие пространства, папки,
          зашифрованные файлы, права доступа и происхождение файлов в одном виде.
          Фильтры помогают упростить демонстрацию.
        </p>

        <GraphLegend />
        <GraphLineLegend />

        <div className="graph-filter-row">
          <button
            className={`graph-filter-btn ${filters.structure ? "active" : ""}`}
            onClick={() => toggleFilter("structure")}
          >
            Структура
          </button>

          <button
            className={`graph-filter-btn ${filters.permissions ? "active" : ""}`}
            onClick={() => toggleFilter("permissions")}
          >
            Доступы
          </button>

          <button
            className={`graph-filter-btn ${filters.lineage ? "active" : ""}`}
            onClick={() => toggleFilter("lineage")}
          >
            Происхождение
          </button>

          <button
            className={`graph-filter-btn risky ${filters.riskyOnly ? "active" : ""}`}
            onClick={() => toggleFilter("riskyOnly")}
          >
            Только риски
          </button>
        </div>

        <div className="react-flow-wrapper">
          {!hasGraphData || nodes.length === 0 ? (
            <div className="empty-state">
              Для выбранных фильтров нет данных. Отключите “Только риски” или запустите демо-сценарии.
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.18 }}
              minZoom={0.2}
              maxZoom={1.5}
            >
              <MiniMap
                nodeColor={(node) => getNodeColor(node.data?.type)}
                pannable
                zoomable
              />
              <Controls />
              <Background gap={18} size={1} />
            </ReactFlow>
          )}
        </div>
      </section>
    </div>
  );
}

export default memo(AccessGraphView);