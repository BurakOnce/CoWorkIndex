# CoWork Index

An enterprise analytics platform that measures how employees use AI tools --
based on behavior, not content. An API + dashboard that produces a usage
maturity score and a behavior archetype for each employee, **without ever
reading or storing prompt content**, using only behavioral meta-signals.

## Why This Project?

Companies are rapidly rolling out AI tools like ChatGPT, Copilot, Claude,
and Cursor to their employees, but they have no way to answer "are we
getting a return on this investment, who is actually using it effectively,
who is just shallow copy-pasting?" The most direct way to measure this --
reading prompt logs -- is both a serious privacy violation and doesn't
scale.

CoWork Index exists to answer this question **without ever seeing a single
character of a prompt or AI output**: it collects only behavioral
meta-signals -- acceptance/rejection rate, dialogue depth, tokens spent,
whether the outcome shipped to production or was abandoned -- and produces
a **usage maturity score** (0-100) and one of 5 behavior archetypes for
each employee. The target audience is HR/People Analytics teams,
engineering managers, and anyone tracking AI adoption.

## What It Offers

- **Usage Maturity Score**: a weighted composite score across 6 dimensions
  (usage intensity, approval/rejection dynamics, dialogue depth,
  communication tone, outcome tracking, critical usage).
- **5 Behavior Archetypes**: Copy-Paster, Dialogue Partner, Skeptic,
  Commander, Passive User -- rules defined in `config/archetype_rules.yaml`.
- **Company / team / employee dashboards**: overview, team comparison,
  employee detail, archetype distribution, time trends.
- **Cost & efficiency layer**: token/USD-based cost and an "efficient
  token ratio" -- which usage actually produced results vs. which was
  wasted.
- **Data quality checks**: write-time validation + periodic audits.
- **Bulk data ingestion**: one-click demo data generation or real data
  import via Excel.
- **EN/TR language support**: switchable from the top-right of the
  dashboard.

Scores are not updated by a batch job -- they update as events arrive
(near-real-time). This project is not a data warehouse, it's a
**service**. For the reasoning behind the architectural decisions
(including why an event-driven OLTP architecture was chosen over a
medallion/batch approach), see [docs/architecture.md](docs/architecture.md).

## How Does Data Get In? (Dashboard > "Data Ingestion")

In a real deployment, this data would normally flow in automatically
through integration with a company's existing HR/People systems (for the
employee roster) and an AI gateway or browser extension (for usage events)
-- not be entered by hand. Since this is a demo/test project without those
integrations, data is instead either generated synthetically or entered
manually via Excel, as described below.

The company roster is currently fixed-size: **50 employees**
(`FIXED_EMPLOYEE_COUNT` in `src/demo_data.py`). The "Data Ingestion" tab
(the rightmost tab in the dashboard) only adds *usage data* (events) to
these 50 employees -- it never creates new employees. Two ways:

1. **Quick Demo Data** -- generates synthetic/test usage data with one
   click (history for the selected number of months, at weekly
   resolution). Intended for demos and development; uses the
   `POST /ingestion/seed-demo-data` endpoint and is fast since it writes
   directly to the DB (no HTTP round-trip).
2. **Real Data Import (Excel)** -- "Download Template" downloads an
   `.xlsx` template listing the existing 50 employees on a reference
   sheet, with a single `events` sheet to fill in and upload
   (`POST /ingestion/import-excel`). This represents the scenario where,
   in a real company, this data typically comes from a periodic export
   from an AI gateway/browser extension's behavioral log --
   **the template contains no content/text column either**. Employees are
   matched only by name against the existing roster (an unmatched row is
   reported as an error, no new employee is created).

## Cost & Efficiency (Token/USD)

Each event's input/output token count is also recorded -- this isn't
content, it's a purely numeric usage measurement, like a file size. Cost
is calculated from per-tool USD prices in `config/pricing.yaml` (per
million tokens) and is **always shown in USD**. The "Cost & Efficiency"
tab in the dashboard shows total cost by company/tool/employee and the
"efficient token ratio" (what share of spent tokens belong to accepted
interactions). This does not change the weights of the existing 6-dimension
maturity score -- it's deliberately kept as a separate, complementary
analysis layer (rationale: [docs/architecture.md](docs/architecture.md)).

**AI tool used**: five options are defined in the `tools` table --
ChatGPT, Copilot, Claude, Cursor, Antigravity (see `src/demo_data.py::TOOLS`,
pricing in `config/pricing.yaml`). Which tool is used can be selected when
generating demo data in the "Data Ingestion" tab; **for now all sample/demo
data is generated through a single tool (Copilot)** -- real diversity will
come with a real integration. This information is shown as the last column
("AI Used") in the relevant dashboard tables (Team Comparison, Employee
Analysis, Cost & Efficiency).

## Project Structure

```
cowork-index/
├── docker-compose.yml         # SQL Server + API + Dashboard (3 services)
├── Dockerfile                  # Shared image for API and dashboard (includes ODBC Driver 18)
├── scripts/
│   ├── ensure_database.py       # Creates the target database if it doesn't exist
│   └── generate_sample_company_excel.py  # Generates a filled sample "company data" file
├── alembic/                    # Schema migrations (incremental)
├── src/
│   ├── main.py                  # FastAPI app + lifespan (scheduler)
│   ├── models.py                 # SQLAlchemy models (3NF)
│   ├── schemas.py                 # Pydantic schemas (the privacy principle is enforced here)
│   ├── db.py                     # engine/session
│   ├── utils.py                    # utcnow() -- naive-UTC timestamp convention
│   ├── demo_data.py                # Synthetic data generation logic (shared)
│   ├── ingestion_service.py         # Demo data generation + bulk Excel import
│   ├── routers/                   # events, scores, quality, ingestion, costs, reference-data
│   ├── scoring_service.py          # 6 dimensions + composite score + archetype
│   ├── cost_service.py             # Token/USD cost + efficiency calculation
│   ├── quality_checks.py           # Periodic data quality audits
│   ├── scheduler.py                # APScheduler job definitions
│   └── event_simulator.py          # Synthetic data generator (HTTP-based CLI)
├── config/
│   ├── weights.yaml                 # Score weights
│   ├── archetype_rules.yaml         # Archetype rules
│   └── pricing.yaml                 # Per-tool USD pricing (per 1M tokens)
├── dashboard/app.py             # Streamlit (an API consumer)
├── docs/                        # architecture.md, data_dictionary.md
└── tests/                       # pytest
```

## API Endpoints

| Method & Path | Description |
|---|---|
| `POST /events` | Records a single interaction event, synchronously updates the score |
| `POST /events/batch` | Bulk event recording |
| `GET /scores/employees` | Current scores for all employees with a computed score |
| `GET /scores/employees/{id}` | An employee's current score and archetype |
| `POST /scores/employees/{id}/recompute` | Manual/historical score computation for a given period |
| `GET /scores/teams/{id}` | Team roll-up |
| `GET /scores/company` | Company-wide summary |
| `GET /scores/trend?period=monthly` | Score trend over time |
| `GET /quality/report` | Latest quality check run |
| `POST /quality/run` | Manually triggers quality checks |
| `POST /ingestion/seed-demo-data` | Generates synthetic/test data with one click |
| `GET /ingestion/template` | Downloads the Excel template for bulk import |
| `POST /ingestion/import-excel` | Bulk-processes a filled-in Excel file |
| `GET /costs/company?window_days=` | Company-wide token/cost (USD) and efficiency summary |
| `GET /costs/employees` | Cost/efficiency summary for all employees |
| `GET /costs/employees/{id}`, `/costs/teams/{id}` | Per-employee/team cost summary |
| `POST/GET /teams`, `/employees`, `/tools` | Reference data CRUD |

## Core Principle

**Behavior is analyzed, not content.** The `interaction_events` table has
no content/text column; the API schema (`extra="forbid"`) rejects such
fields at the code level. For details and a **visual ER diagram of the
database schema**, see [docs/data_dictionary.md](docs/data_dictionary.md).
