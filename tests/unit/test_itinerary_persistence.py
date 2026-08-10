"""Unit tests for Stage 9 itinerary persistence (service + repository mapping)."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import uuid4

from app.modules.agent_orchestration.application.use_cases.itinerary_service import (
    ItineraryService,
)
from app.modules.agent_orchestration.domain.itinerary import Itinerary


class _RecordingItineraryRepo:
    """In-memory stand-in for IItineraryRepository."""

    def __init__(self) -> None:
        self.added: list[Itinerary] = []

    async def get_by_id(self, entity_id):
        return next((i for i in self.added if i.id == entity_id), None)

    async def get_latest_for_session(self, session_id):
        items = [i for i in self.added if i.session_id == session_id]
        return max(items, key=lambda i: i.created_at, default=None)

    async def list_for_session(self, session_id):
        return sorted(
            (i for i in self.added if i.session_id == session_id),
            key=lambda i: i.created_at,
            reverse=True,
        )

    async def add(self, entity: Itinerary) -> Itinerary:
        self.added.append(entity)
        return entity

    async def update(self, entity: Itinerary) -> Itinerary:  # pragma: no cover
        return entity

    async def delete(self, entity_id) -> None:
        self.added = [i for i in self.added if i.id != entity_id]


class _UoW:
    def __init__(self, repo: _RecordingItineraryRepo) -> None:
        self.itineraries = repo
        self.committed = False

    async def __aenter__(self) -> _UoW:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:  # pragma: no cover
        pass


def _service(repo: _RecordingItineraryRepo) -> tuple[ItineraryService, list[_UoW]]:
    uows: list[_UoW] = []

    def factory() -> _UoW:
        u = _UoW(repo)
        uows.append(u)
        return u

    return ItineraryService(uow_factory=factory), uows


async def test_save_completed_persists_full_entity():
    repo = _RecordingItineraryRepo()
    service, uows = _service(repo)
    sid, uid = str(uuid4()), str(uuid4())

    saved = await service.save_completed(
        session_id=sid,
        user_id=uid,
        itinerary="# 3 days in Atlantis\n...",
        requirements={"destination_city": "Atlantis", "num_days": 3, "budget": "$1500"},
        clusters=[{"day": 1, "stops": [{"name": "Poseidon Temple"}], "legs": []}],
    )

    assert saved is not None
    assert repo.added and uows[-1].committed
    entity = repo.added[0]
    assert entity.session_id == uuid.UUID(sid)
    assert entity.user_id == uuid.UUID(uid)
    assert entity.content.startswith("# 3 days")
    assert entity.num_days == 3
    assert entity.destination_label == "Atlantis"
    assert entity.clusters[0]["stops"][0]["name"] == "Poseidon Temple"


async def test_save_completed_noop_without_itinerary():
    repo = _RecordingItineraryRepo()
    service, _ = _service(repo)

    result = await service.save_completed(
        session_id=str(uuid4()),
        user_id=str(uuid4()),
        itinerary=None,
        requirements={},
        clusters=[],
    )
    assert result is None
    assert repo.added == []


async def test_save_completed_swallows_bad_ids():
    repo = _RecordingItineraryRepo()
    service, _ = _service(repo)

    result = await service.save_completed(
        session_id="not-a-uuid",
        user_id="also-not",
        itinerary="some plan",
        requirements={},
        clusters=[],
    )
    assert result is None
    assert repo.added == []


async def test_get_latest_for_session_returns_newest():
    repo = _RecordingItineraryRepo()
    service, _ = _service(repo)
    sid = uuid4()
    older = Itinerary(session_id=sid, user_id=uuid4(), content="v1")
    newer = Itinerary(session_id=sid, user_id=uuid4(), content="v2")
    # Force distinct timestamps.
    repo.added.extend([older, newer])

    latest = await service.get_latest_for_session(sid)
    assert latest is not None and latest.content == "v2"


def test_itinerary_entity_defaults():
    it = Itinerary(session_id=uuid4(), user_id=uuid4(), content="x")
    assert it.requirements == {}
    assert it.clusters == []
    assert it.num_days is None
    assert it.destination_label is None
