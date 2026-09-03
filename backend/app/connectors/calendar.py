from abc import ABC, abstractmethod
from datetime import datetime

from sqlmodel import Session, select

from ..models import CalendarEvent


class CalendarProvider(ABC):
    @abstractmethod
    def get_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

    @abstractmethod
    def create_event(self, event: CalendarEvent) -> CalendarEvent: ...


class LocalCalendarProvider(CalendarProvider):
    def __init__(self, session: Session):
        self.session = session

    def get_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return list(self.session.exec(select(CalendarEvent).where(CalendarEvent.end_at > start, CalendarEvent.start_at < end)).all())

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event
