"""Bounded, short-lived pagination snapshots; never a provider freshness signal."""

import re
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from teamarr.core.controller_feed import FeedEntry, FeedQuery, FeedResponse


class SnapshotExpired(ValueError):
    pass


@dataclass
class Snapshot:
    query: FeedQuery
    items: list[FeedEntry]
    created_at: datetime
    expires_at: datetime


class FeedSnapshotStore:
    """Process-local; multiple workers/replicas require sticky routing for cursors."""

    def __init__(self, ttl_seconds: int = 180, max_snapshots: int = 32, max_items: int = 10000):
        self.ttl_seconds = ttl_seconds
        self.max_snapshots = max_snapshots
        self.max_items = max_items
        self._snapshots: OrderedDict[str, Snapshot] = OrderedDict()
        self._lock = threading.Lock()

    def create(self, query: FeedQuery, items: list[FeedEntry]) -> FeedResponse:
        if len(items) > self.max_items:
            raise ValueError("Feed exceeds snapshot limit; narrow the window or sources")
        now = datetime.now(UTC)
        snapshot = Snapshot(
            query.model_copy(deep=True),
            [item.model_copy(deep=True) for item in items],
            now,
            now + timedelta(seconds=self.ttl_seconds),
        )
        key = secrets.token_urlsafe(24)
        with self._lock:
            for expired in [k for k, s in self._snapshots.items() if s.expires_at <= now]:
                del self._snapshots[expired]
            self._snapshots[key] = snapshot
            while len(self._snapshots) > self.max_snapshots:
                self._snapshots.popitem(last=False)
        return self._page(key, snapshot, 0)

    def page(self, cursor: str) -> FeedResponse:
        match = re.fullmatch(r"([A-Za-z0-9_-]{32})\.(\d{1,8})", cursor)
        if not match:
            raise ValueError("Invalid feed cursor")
        key, offset_text = match.groups()
        with self._lock:
            snapshot = self._snapshots.get(key)
            if snapshot is None or snapshot.expires_at <= datetime.now(UTC):
                self._snapshots.pop(key, None)
                raise SnapshotExpired("Feed snapshot expired or unavailable; restart the query")
            offset = int(offset_text)
            if offset <= 0 or offset >= len(snapshot.items) or offset % snapshot.query.limit:
                raise ValueError("Invalid feed cursor offset")
            return self._page(key, snapshot, offset)

    @staticmethod
    def _page(key: str, snapshot: Snapshot, offset: int) -> FeedResponse:
        end = offset + snapshot.query.limit
        items = snapshot.items[offset:end]
        return FeedResponse(
            query=snapshot.query,
            snapshot_created_at=snapshot.created_at,
            snapshot_expires_at=snapshot.expires_at,
            total=len(snapshot.items),
            count=len(items),
            items=items,
            next_cursor=f"{key}.{end}" if end < len(snapshot.items) else None,
        ).model_copy(deep=True)
