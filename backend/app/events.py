from typing import Optional
from uuid import uuid4

from sqlmodel import Session

from .models import DomainEvent


def emit_event(
    session: Session,
    event_type: str,
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    payload: Optional[dict] = None,
    correlation_id: Optional[str] = None,
) -> DomainEvent:
    event = DomainEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
        correlation_id=correlation_id or str(uuid4()),
    )
    session.add(event)
    session.flush()
    return event
