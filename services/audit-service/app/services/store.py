from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.schemas.audit import AuditLogCreate, AuditLogOut


class AuditStore:
    def __init__(self) -> None:
        self._items: list[AuditLogOut] = []

    def add(self, payload: AuditLogCreate) -> AuditLogOut:
        item = AuditLogOut(
            id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            **payload.model_dump(),
        )
        self._items.append(item)
        return item

    def list_by_resource(self, resource_type: str, resource_id: str, limit: int = 50) -> list[AuditLogOut]:
        return [
            item
            for item in reversed(self._items)
            if item.resource_type == resource_type and item.resource_id == resource_id
        ][:limit]

    def list_recent(
        self,
        *,
        limit: int = 100,
        action: str | None = None,
        user_id: str | None = None,
    ) -> list[AuditLogOut]:
        normalized_user = (user_id or '').strip()
        normalized_action = (action or '').strip()
        results: list[AuditLogOut] = []
        for item in reversed(self._items):
            if normalized_action and item.action != normalized_action:
                continue
            if normalized_user and item.user_id != normalized_user:
                continue
            results.append(item)
            if len(results) >= max(int(limit), 1):
                break
        return results


audit_store = AuditStore()
