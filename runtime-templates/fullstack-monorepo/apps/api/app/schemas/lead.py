from pydantic import BaseModel


class LeadCreate(BaseModel):
    name: str
    email: str
