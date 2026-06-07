"""Concrete KB destination repository backed by PostgreSQL."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.postgres.models.kb_destination_model import KBDestinationORM
from app.modules.agent_orchestration.application.ports.kb_destination_repository_port import (
    IKBDestinationRepository,
)
from app.modules.agent_orchestration.domain.kb_destination import KBDestination


class KBDestinationRepository(IKBDestinationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(orm: KBDestinationORM) -> KBDestination:
        return KBDestination.model_validate(orm)

    @staticmethod
    def _apply(orm: KBDestinationORM, entity: KBDestination) -> None:
        orm.destination_key = entity.destination_key
        orm.city = entity.city
        orm.country = entity.country
        orm.status = entity.status
        orm.doc_count = entity.doc_count
        orm.error_message = entity.error_message
        orm.indexed_at = entity.indexed_at

    async def get_by_id(self, entity_id: UUID) -> KBDestination | None:
        orm = await self._session.get(KBDestinationORM, entity_id)
        return self._to_domain(orm) if orm else None

    async def get_by_key(self, destination_key: str) -> KBDestination | None:
        stmt = select(KBDestinationORM).where(
            KBDestinationORM.destination_key == destination_key
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def add(self, entity: KBDestination) -> KBDestination:
        orm = KBDestinationORM(
            id=entity.id,
            destination_key=entity.destination_key,
            city=entity.city,
            country=entity.country,
            status=entity.status,
            doc_count=entity.doc_count,
            error_message=entity.error_message,
            indexed_at=entity.indexed_at,
        )
        self._session.add(orm)
        await self._session.flush()
        return self._to_domain(orm)

    async def update(self, entity: KBDestination) -> KBDestination:
        orm = await self._session.get(KBDestinationORM, entity.id)
        if orm is None:
            raise ValueError(f"KBDestination {entity.id} not found")
        self._apply(orm, entity)
        await self._session.flush()
        return self._to_domain(orm)

    async def upsert(self, entity: KBDestination) -> KBDestination:
        existing = await self.get_by_key(entity.destination_key)
        if existing is None:
            return await self.add(entity)
        orm = await self._session.get(KBDestinationORM, existing.id)
        assert orm is not None  # noqa: S101 - guaranteed by get_by_key hit
        self._apply(orm, entity)
        await self._session.flush()
        return self._to_domain(orm)

    async def delete(self, entity_id: UUID) -> None:
        orm = await self._session.get(KBDestinationORM, entity_id)
        if orm:
            await self._session.delete(orm)
            await self._session.flush()
