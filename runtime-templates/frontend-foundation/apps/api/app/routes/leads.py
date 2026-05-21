from fastapi import APIRouter

from app.schemas.lead import LeadCreate
from app.services.lead_capture_service import capture_lead

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.post("")
async def create_lead(payload: LeadCreate) -> dict[str, object]:
    return {"status": "accepted", "lead": capture_lead(payload)}
