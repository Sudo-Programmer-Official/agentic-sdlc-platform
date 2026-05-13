| Layer | Technology |
|---|---|
| Frontend | Vue 3, TypeScript, Element Plus, Tailwind CSS, Vite |
| Backend | FastAPI, Pydantic, SQLAlchemy (async) |
| AI Runtime | OpenAI client integration with policy/budget routing and executor contracts |
| Database | PostgreSQL + Alembic migrations |
| Queue / Scheduler | Runtime scheduler service + orchestrator + worker lease model |
| Testing Framework | Pytest (API/runtime tests), project test commands (e.g., `pytest -q`) |
| Version Control | Git + GitHub provider integration |
| Deployment Platform | Docker Compose-based multi-service deployment (api/scheduler/worker/web/db) |
