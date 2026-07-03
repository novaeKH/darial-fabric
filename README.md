# Takt

**Enterprise AI Control Center for observability, FinOps and governance**

Takt helps companies understand which AI systems are running, how much they cost, what business result they produce and where operational or policy risks appear.

## Problem

As companies adopt more AI agents and LLM products, monitoring remains fragmented across teams. Management cannot easily answer:

- which AI systems are active;
- who owns them;
- how much they cost;
- which runs create value;
- where waste and policy violations occur.

## What Takt provides

- registry of AI products, agents and deployments;
- dev/prod environment tracking;
- telemetry API keys;
- run and LLM-call tracing;
- token and latency accounting;
- server-side cost calculation;
- cost per run and cost per outcome;
- waste and retry analysis;
- business outcomes, time saved and estimated business value;
- governance policies and violations;
- RBAC for Admin, Product Owner, FinOps, Security and Auditor;
- management reports with CSV and PDF export.

## Product flow

```text
Registry → Telemetry → Runs → Cost → Outcome → Governance → Report
```

## Demo

A resume-review agent processes a real CV and sends telemetry to Takt. Takt records:

- model and provider;
- input/output tokens;
- latency;
- run cost;
- business outcome;
- estimated value;
- policy violations.

## Roles

| Role | Access |
|---|---|
| Administrator | Full access |
| AI Product Owner | Products, runs, economics, reports |
| AI FinOps | Costs, budgets, runs, reports |
| Security | Policies, violations, integrations, audit |
| External Auditor | Read-only reports, risks, policies, audit |

## Tech stack

- FastAPI
- PostgreSQL
- Redis
- React
- Docker Compose
- Python telemetry SDK

## Quick start

```bash
git clone <YOUR_REPOSITORY_URL>
cd takt-ai-control-center
docker compose up --build -d
```

Open:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000/docs`

## Verification

```bash
./scripts/final_smoke_test.sh
```

Expected result:

```text
FINAL RESULT: PASS
```

## Current limitations

- single-organization mode;
- no SSO/SAML/OIDC;
- no full multi-tenancy;
- tool cost may be provided by integration;
- business value is estimated;
- no automatic currency conversion;
- no production Kafka/ClickHouse/Kubernetes deployment.

## Positioning

Takt differs from traditional security tools by connecting AI risk with cost and business outcome.

It differs from pure LLM observability platforms by adding:

- product ownership;
- budgets;
- cost per outcome;
- waste;
- business value;
- corporate roles;
- management reporting.

## License

Educational MVP.
