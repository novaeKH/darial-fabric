# README_FINAL.md

# Darial — Enterprise AI Control Center

Darial — платформа централизованного контроля корпоративных AI-систем.

## Основные возможности MVP

- реестр AI-продуктов, агентов и deployment;
- telemetry API key для каждого источника;
- приём run, LLM, tool, error и outcome событий;
- серверный расчёт стоимости LLM;
- Run Details с полной трассировкой;
- AI FinOps: расходы, бюджеты, waste и прогноз;
- Governance: политики, нарушения и аудит;
- RBAC с backend-проверкой разрешений;
- управленческий отчёт и экспорт CSV/PDF;
- synthetic worker для демонстрационных данных.

## Архитектура

```text
AI product / Agent SDK
          |
          v
Telemetry ingestion API
          |
          v
PostgreSQL + ingestion worker
          |
          v
Observability / Economics / Governance
          |
          v
Dashboard + Run Details + Management Report
```

## Экономические формулы

### Облачная LLM

```text
Input cost =
  uncached_input_tokens × input_price_per_million / 1 000 000

Cached cost =
  cached_tokens × cached_price_per_million / 1 000 000

Output cost =
  standard_output_tokens × output_price_per_million / 1 000 000

Reasoning cost =
  reasoning_tokens × reasoning_price_per_million / 1 000 000
```

Cached tokens считаются подмножеством input tokens.

Reasoning tokens считаются подмножеством output tokens.

### Стоимость запуска

```text
Run cost = LLM cost + Tool cost + Other registered cost
```

### Полезный результат

Outcome учитывается, когда:

```text
success = true
AND human_accepted != false
```

Количество полезных результатов берётся из `quantity`.

### Управленческие метрики

```text
Cost per run = Total cost / Runs
```

```text
Cost per outcome = Total cost / Successful outcome quantity
```

```text
Net effect = Estimated business value - Total cost
```

```text
ROI = Net effect / Total cost
```

## Матрица ролей

### Administrator

Полный доступ.

### AI Product Owner

Продукты, агенты, запуски, экономика и отчёты.

### AI FinOps

Экономика, бюджеты, запуски и отчёты.

### Security

Политики, нарушения, аудит и интеграции.

### External Auditor

Read-only:

- отчёты;
- риски;
- политики;
- аудит.

## Ограничения MVP

- одна организация;
- нет SSO/SAML/OIDC;
- нет полноценного multi-tenancy;
- стоимость tools может передаваться интеграцией;
- business value и time saved являются оценочными показателями;
- нет ClickHouse/Kafka production-контура;
- нет Kubernetes и mTLS;
- нет автоматической конвертации валют;
- synthetic data используется только для демонстрации.

## Запуск

```bash
docker compose up --build -d
```

Frontend:

```text
http://localhost:5173
```

Backend:

```text
http://localhost:8000
```

## Финальная проверка

```bash
./scripts/final_smoke_test.sh
```
