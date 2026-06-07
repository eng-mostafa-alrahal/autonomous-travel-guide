"""KB status use-cases — track destination indexing lifecycle in kb_destinations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.modules.agent_orchestration.domain.kb_destination import KBDestination, KBStatus
from app.shared.ports.unit_of_work import IUnitOfWork


class KBStatusService:
    def __init__(self, uow_factory: Callable[[], IUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def get_status(self, destination_key: str) -> KBDestination | None:
        async with self._uow_factory() as uow:
            return await uow.kb_destinations.get_by_key(destination_key)  # type: ignore[attr-defined]

    async def mark_building(
        self, *, destination_key: str, city: str | None, country: str | None
    ) -> KBDestination:
        return await self._upsert(
            destination_key=destination_key,
            city=city,
            country=country,
            status="building",
        )

    async def mark_ready(
        self,
        *,
        destination_key: str,
        city: str | None,
        country: str | None,
        doc_count: int,
    ) -> KBDestination:
        return await self._upsert(
            destination_key=destination_key,
            city=city,
            country=country,
            status="ready",
            doc_count=doc_count,
            indexed_at=datetime.now(UTC),
        )

    async def mark_failed(
        self,
        *,
        destination_key: str,
        city: str | None,
        country: str | None,
        error_message: str,
    ) -> KBDestination:
        return await self._upsert(
            destination_key=destination_key,
            city=city,
            country=country,
            status="failed",
            error_message=error_message,
        )

    async def _upsert(
        self,
        *,
        destination_key: str,
        city: str | None,
        country: str | None,
        status: KBStatus,
        doc_count: int = 0,
        error_message: str | None = None,
        indexed_at: datetime | None = None,
    ) -> KBDestination:
        async with self._uow_factory() as uow:
            entity = KBDestination(
                destination_key=destination_key,
                city=city,
                country=country,
                status=status,
                doc_count=doc_count,
                error_message=error_message,
                indexed_at=indexed_at,
            )
            result = await uow.kb_destinations.upsert(entity)  # type: ignore[attr-defined]
            await uow.commit()
            return result
