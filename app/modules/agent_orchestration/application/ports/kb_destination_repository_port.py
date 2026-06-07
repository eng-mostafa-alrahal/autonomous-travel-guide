"""KB destination repository contract — extends the generic IRepository."""

from __future__ import annotations

from abc import abstractmethod

from app.modules.agent_orchestration.domain.kb_destination import KBDestination
from app.shared.ports.base_repository import IRepository


class IKBDestinationRepository(IRepository[KBDestination]):
    @abstractmethod
    async def get_by_key(self, destination_key: str) -> KBDestination | None: ...

    @abstractmethod
    async def upsert(self, entity: KBDestination) -> KBDestination:
        """Insert or update a destination keyed by ``destination_key``."""
        ...
