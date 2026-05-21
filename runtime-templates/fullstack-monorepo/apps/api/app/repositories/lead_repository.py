from typing import TypedDict


class LeadRecord(TypedDict):
    name: str
    email: str


_LEADS: list[LeadRecord] = []


def save_lead(name: str, email: str) -> LeadRecord:
    record: LeadRecord = {"name": name, "email": email}
    _LEADS.append(record)
    return record
