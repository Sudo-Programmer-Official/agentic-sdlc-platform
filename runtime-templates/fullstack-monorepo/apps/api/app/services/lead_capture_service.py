from app.repositories.lead_repository import save_lead
from app.schemas.lead import LeadCreate


def capture_lead(payload: LeadCreate) -> dict[str, str]:
    return save_lead(name=payload.name, email=payload.email)
