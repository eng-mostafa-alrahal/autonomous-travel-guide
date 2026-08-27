"""Concrete itinerary repository backed by PostgreSQL."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.postgres.models.itinerary_model import ItineraryORM
from app.modules.agent_orchestration.application.ports.itinerary_repository_port import (
    IItineraryRepository,
)
from app.modules.agent_orchestration.domain.itinerary import Itinerary


class ItineraryRepository(IItineraryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(orm: ItineraryORM) -> Itinerary:
        return Itinerary.model_validate(orm)

    async def get_by_id(self, entity_id: UUID) -> Itinerary | None:
        orm = await self._session.get(ItineraryORM, entity_id)
        return self._to_domain(orm) if orm else None

    async def get_latest_for_session(self, session_id: UUID) -> Itinerary | None:
        stmt = (
            select(ItineraryORM)
            .where(ItineraryORM.session_id == session_id)
            .order_by(ItineraryORM.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def list_for_session(self, session_id: UUID) -> list[Itinerary]:
        stmt = (
            select(ItineraryORM)
            .where(ItineraryORM.session_id == session_id)
            .order_by(ItineraryORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(orm) for orm in result.scalars().all()]

    async def add(self, entity: Itinerary) -> Itinerary:
        orm = ItineraryORM(
            id=entity.id,
            session_id=entity.session_id,
            user_id=entity.user_id,
            content=entity.content,
            requirements=entity.requirements,
            clusters=entity.clusters,
            num_days=entity.num_days,
            destination_label=entity.destination_label,
        )
        self._session.add(orm)
        await self._session.flush()
        return self._to_domain(orm)

    async def update(self, entity: Itinerary) -> Itinerary:
        orm = await self._session.get(ItineraryORM, entity.id)
        if orm is None:
            raise ValueError(f"Itinerary {entity.id} not found")
        orm.content = entity.content
        orm.requirements = entity.requirements
        orm.clusters = entity.clusters
        orm.num_days = entity.num_days
        orm.destination_label = entity.destination_label
        await self._session.flush()
        return self._to_domain(orm)

    async def delete(self, entity_id: UUID) -> None:
        orm = await self._session.get(ItineraryORM, entity_id)
        if orm:
            await self._session.delete(orm)
            await self._session.flush()
