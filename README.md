# Takt

**Enterprise AI Control Center для наблюдаемости, экономики и управления корпоративными AI-системами.**

Takt ведёт единый реестр AI-продуктов и агентов, принимает телеметрию их запусков, рассчитывает стоимость LLM-вызовов, связывает расходы с бизнес-результатами и фиксирует нарушения политик.

```text
Registry → Telemetry → Runs → Cost → Outcome → Governance → Report
```

## Основные возможности

| Модуль | Что входит |
|---|---|
| AI Registry | AI-продукты, агенты, deployments, версии, dev/stage/prod, команды-владельцы, критичность и model endpoints |
| Onboarding | Мастер подключения создаёт Product, Agent, Deployment, тариф модели, ingestion source и отдельный telemetry API key |
| Telemetry | Приём одиночных и пакетных событий: `agent_run`, `llm_call`, `tool_call`, `business_outcome` |
| Observability | Список запусков, Run Details, LLM- и tool-вызовы, токены, latency, ошибки, retries и итоговый outcome |
| AI FinOps | Стоимость запуска, стоимость результата, waste, бюджеты, прогноз расходов и распределение затрат по продуктам и агентам |
| AI Value | Quality score, human acceptance, time saved, estimated business value, net effect и ROI |
| Governance | Политики, версии правил, импорт/экспорт, журнал изменений, нарушения и статусы обработки |
| Reporting | Управленческий отчёт за период, динамика расходов, рейтинги продуктов и агентов, CSV и печать в PDF |
| RBAC | Backend- и frontend-проверки прав для администратора, владельца продукта, FinOps, Security и внешнего аудитора |
| Integrations | REST ingestion API, Python SDK, optional Kafka/Redpanda pipeline и ClickHouse mirror |

## Как формируется стоимость

Стоимость LLM-вызова рассчитывается на backend по активному тарифу `ModelEndpoint`.

```text
LLM cost =
  uncached input tokens × input price
+ cached input tokens × cached price
+ standard output tokens × output price
+ reasoning tokens × reasoning price
+ GPU seconds × GPU hour price / 3600
```

В модели данных:

- `cached_tokens` входят в `input_tokens`;
- `reasoning_tokens` входят в `output_tokens`;
- специальные тарифы для cached/reasoning при нулевом значении заменяются базовыми тарифами;
- стоимость tool call передаётся интеграцией и хранится с отметкой о происхождении.

Полезным результатом считается outcome с `success=true`, если он не был явно отклонён человеком (`human_accepted=false`).

```text
Cost per outcome = total cost / successful outcome quantity
Net effect       = estimated business value - total cost
ROI              = net effect / total cost
```

`Waste` включает стоимость failed/cancelled runs, технически успешных запусков с отклонёнными outcomes и переданный интеграцией `retry_cost`.

## Поток телеметрии

```text
AI agent / LLM application
        │
        ├── Python SDK
        └── REST events / batch
                 │
                 ▼
         FastAPI ingestion API
   API key · scope · sanitization · deduplication
                 │
                 ▼
       PostgreSQL ingestion_events
                 │
                 ▼
           ingestion-worker
        retry · backoff · dead letter
                 │
                 ├── AgentRun
                 ├── LLMCall
                 ├── ToolCall
                 └── BusinessOutcome
                 │
                 ▼
     Dashboard · budgets · policies · reports
```

Для расширенного локального контура предусмотрены compose-overlays:

- Redpanda/Kafka;
- Kafka consumer и PostgreSQL outbox publisher;
- Kafka DLQ и replay;
- health snapshots;
- ClickHouse mirror для telemetry entities.

## Защита телеметрии

Каждый ingestion source получает отдельный ключ с привязкой к продукту и окружению.

Поддерживаются:

- хранение ключа в виде hash и prefix;
- одноразовый показ полного ключа;
- срок действия;
- ротация и отзыв;
- allowlist типов событий;
- rate limit;
- запрет отправки события от имени другого продукта;
- дедупликация по `source_id + event_id`;
- очистка чувствительных полей;
- обрезка строк длиннее 4096 символов.

SDK и ingestion API заменяют значения полей `authorization`, `api_key`, `token`, `password`, `secret`, `prompt`, `response`, `tool_args` и других чувствительных ключей на `[REDACTED]`.

## Роли

| Роль | Доступ |
|---|---|
| Администратор | Все разделы и управление платформой |
| Владелец AI-продукта | Продукты, агенты, запуски, экономика, риски и отчёты |
| AI FinOps | Продукты, запуски, экономика, бюджеты и отчёты |
| Информационная безопасность | Продукты, запуски, политики, нарушения, интеграции и аудит |
| Внешний аудитор | Read-only: отчёты, риски, политики и аудит |

Права проверяются middleware на backend. Скрытие разделов в интерфейсе не заменяет проверку API: запрещённые запросы возвращают `403`.

## Технологии

### Backend

- Python 3.11
- FastAPI
- SQLAlchemy 2
- PostgreSQL 16
- Pydantic
- Redis
- MinIO
- ClickHouse
- Redpanda / Kafka

### Frontend

- React 18
- Vite
- Axios
- Lucide React
- XYFlow

### Инфраструктура

- Docker Compose
- ingestion worker
- synthetic data worker
- Kafka consumer / outbox / DLQ workers
- Python telemetry SDK

## Структура проекта

```text
.
├── backend/
│   ├── app/
│   │   ├── api/                 # REST API
│   │   ├── models/              # SQLAlchemy models
│   │   ├── services/            # economics, reports, files, policies
│   │   ├── workers/             # background workers
│   │   ├── ingestion_worker.py
│   │   └── main.py
│   └── tests/
├── frontend/
│   └── src/
│       ├── ObservabilityDashboard.jsx
│       ├── ControlCenterViews.jsx
│       ├── RunDetailsDrawer.jsx
│       ├── BudgetView.jsx
│       ├── PoliciesView.jsx
│       ├── ViolationsView.jsx
│       ├── IntegrationsView.jsx
│       └── ReportsView.jsx
├── sdk/
│   ├── darial_sdk/
│   ├── send_demo_telemetry.py
│   └── tests/
├── mvp_readiness/
├── scripts/
├── docker-compose.yml
└── docker-compose.*.yml
```

## Быстрый запуск

### Требования

- Docker Desktop;
- Docker Compose v2;
- свободные порты `5173`, `8000`, `5432`, `6379`, `9000`, `9001`.

### 1. Клонирование

```bash
git clone https://github.com/novaeKH/takt-ai-control-center.git
cd takt-ai-control-center
```

### 2. Конфигурация

```bash
cp backend/.env.example backend/.env
```

Значения из `.env.example` предназначены для локального запуска. Для внешнего окружения необходимо заменить `SECRET_KEY`, `MASTER_KEK`, пароли PostgreSQL и MinIO.

### 3. Запуск базового контура

```bash
docker compose up --build -d
docker compose ps
```

### 4. Инициализация демо-данных

```bash
docker compose exec backend python -m app.seed
docker compose exec backend python -m app.observability_seed
docker compose exec backend python -m app.seed_rbac
docker compose exec backend python -m app.bootstrap_rbac_users
docker compose exec backend python -m app.seed_demo_policies
docker compose exec backend python -m app.demo_telemetry_seed --days 30
```

Команды создают:

- команды и агентов;
- три AI-продукта и prod deployments;
- тариф модели;
- 30 дней запусков, LLM/tool calls и outcomes;
- бюджеты;
- governance policies;
- пять RBAC-ролей и демонстрационных пользователей.

### 5. Адреса

| Сервис | URL |
|---|---|
| Web UI | http://localhost:5173 |
| Swagger / OpenAPI | http://localhost:8000/docs |
| Backend health | http://localhost:8000/api/health |
| MinIO API | http://localhost:9000 |
| MinIO Console | http://localhost:9001 |

В интерфейсе выберите пользователя **Takt Administrator**.

### Остановка

```bash
docker compose down
```

Удаление локальных volumes вместе с данными:

```bash
docker compose down -v
```

## Расширенный локальный контур

Скрипт запускает базовые сервисы, Redpanda/Kafka, consumer, outbox publisher, DLQ worker, health snapshots и ClickHouse:

```bash
chmod +x start.sh stop.sh
./start.sh
```

Дополнительные адреса:

| Сервис | URL / адрес |
|---|---|
| Redpanda external broker | `localhost:19092` |
| Redpanda Console | http://localhost:8088 |
| ClickHouse HTTP | http://localhost:8123 |

Остановка:

```bash
./stop.sh
```

## Подключение AI-агента

Через раздел **Продукты → Подключить AI-систему** создаются продукт, агент, deployment, модель, ingestion source и API key. После завершения мастер показывает готовый Python snippet.

Для локального SDK:

```bash
export PYTHONPATH="$PWD/sdk"
export DARIAL_BASE_URL="http://localhost:8000"
export DARIAL_API_KEY="dr_..."
```

Пример интеграции:

```python
from darial_sdk import DarialClient

client = DarialClient.from_env()

with client.run(
    workflow="contract-review",
    agent_name="Legal Contract Agent",
    product_id="PRODUCT_ID",
    environment="prod",
) as run:
    run.record_tool_call(
        tool_name="s3_document_reader",
        latency_ms=180,
    )

    run.record_llm_call(
        provider="internal",
        model_name="qwen-72b-demo",
        input_tokens=4200,
        output_tokens=630,
        latency_ms=6100,
    )

    run.record_outcome(
        outcome_type="contract_review_completed",
        success=True,
        quality_score=0.94,
        human_accepted=True,
        time_saved_minutes=24,
        estimated_business_value=850,
    )
```

Готовый пример:

```bash
PYTHONPATH=sdk python sdk/send_demo_telemetry.py \
  --api-key "$DARIAL_API_KEY" \
  --product-id "PRODUCT_ID" \
  --agent-name "Legal Contract Agent"
```

## Основные API

### Registry

```text
POST /api/ai-products
GET  /api/ai-products
POST /api/agents
POST /api/agent-deployments
GET  /api/agent-deployments
POST /api/model-endpoints
GET  /api/model-endpoints
```

### Telemetry

```text
POST /api/ingestion/sources
POST /api/ingestion/sources/{source_id}/keys
POST /api/ingestion/events
POST /api/ingestion/events/batch
GET  /api/ingestion/events
GET  /api/ingestion/summary
```

### Observability and economics

```text
GET /api/observability/dashboard/summary
GET /api/observability/runs
GET /api/observability/runs/{run_id}/details
GET /api/observability/agents/summary
GET /api/observability/budgets/summary
GET /api/observability/reports/management
GET /api/observability/reports/management.csv
```

### Governance and access

```text
GET   /api/observability/policies
POST  /api/observability/policies
POST  /api/observability/policies/evaluate
GET   /api/observability/violations
PATCH /api/observability/violations/{violation_id}/status
GET   /api/rbac/summary
GET   /api/rbac/principals
GET   /api/rbac/roles
```

Полный контракт доступен в Swagger.

## Проверка проекта

Unit-тесты экономики:

```bash
PYTHONPATH=backend python -m unittest \
  backend/tests/test_economics_formulas.py -v
```

Unit-тесты SDK:

```bash
PYTHONPATH=sdk python -m unittest \
  sdk/tests/test_sdk.py -v
```

Проверка запущенного проекта:

```bash
chmod +x scripts/final_smoke_test.sh
./scripts/final_smoke_test.sh
```

Скрипт проверяет:

- состояние Docker Compose;
- frontend и OpenAPI;
- компиляцию backend;
- production build frontend;
- наличие RBAC principals;
- права External Auditor;
- основные admin endpoints;
- ошибки в логах;
- попадание secret-файлов в Git.

## Демо-сценарии

В демо-данных используются три AI-продукта:

| Продукт | Сценарий |
|---|---|
| Legal Contract Analyzer | Анализ договоров, LLM usage, tool calls и подтверждённый business outcome |
| Procurement Assistant | Повторные вызовы, failed runs, waste и бюджетные отклонения |
| Internal Knowledge RAG | Поиск по внутренней базе знаний и governance violations |

## Дополнительный файловый модуль

В кодовой базе сохранён модуль контроля файловых workflow:

- workspaces, folders и files;
- MinIO storage;
- шифрование файлов;
- временные разрешения;
- security scan и quarantine;
- file lineage;
- access graph;
- audit log.

Модуль используется как отдельный security-контур и не является главным сценарием интерфейса Darial.
