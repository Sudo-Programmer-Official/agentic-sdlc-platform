from fastapi import FastAPI

from app.routes.health import router as health_router
from app.routes.leads import router as leads_router


app = FastAPI(title="Agentic Runtime API", version="0.1.0")
app.include_router(health_router)
app.include_router(leads_router)
