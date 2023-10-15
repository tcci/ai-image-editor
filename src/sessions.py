from __future__ import annotations as _annotations

from datetime import datetime, timedelta
from uuid import uuid4
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import Form, HTTPException


@dataclass(slots=True)
class Session:
    session_id: str
    width: int
    height: int
    mode: str
    # conversation: list[dict[str, str]] = field(default_factory=list)
    last_active: datetime = field(default_factory=datetime.utcnow)
    tmp_images: list[Path] = field(default_factory=list)


class Sessions:
    _max_age = timedelta(minutes=5)

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def add_new(self, width: int, height: int, mode: str) -> Session:
        session_id = uuid4().hex
        session = Session(session_id=session_id, width=width, height=height, mode=mode)
        self._sessions[session_id] = session
        return session

    def remove_old_sessions(self) -> None:
        now = datetime.utcnow()
        to_remove: list[Session] = []

        for session in self._sessions.values():
            if now - session.last_active > self._max_age:
                to_remove.append(session)

        for session in to_remove:
            for path in session.tmp_images:
                path.unlink(missing_ok=True)
            del self._sessions[session.session_id]

    async def get(self, session_id: Annotated[str, Form()]) -> Session:
        try:
            session = self._sessions[session_id]
        except KeyError:
            raise HTTPException(status_code=404, detail='Image not found')
        else:
            session.last_active = datetime.utcnow()
            self.remove_old_sessions()
            return session


sessions = Sessions()
