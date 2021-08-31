from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import Any, AsyncContextManager, Callable, Iterable, List, Optional, Set, Type
from uuid import UUID

from anyio import to_thread
from anyio.from_thread import BlockingPortal

from . import events
from .abc import AsyncDataStore, DataStore
from .events import Event, SubscriptionToken
from .policies import ConflictPolicy
from .structures import Job, JobResult, Schedule
from .util import reentrant


@reentrant
@dataclass
class AsyncDataStoreAdapter(AsyncDataStore):
    original: DataStore
    _portal: BlockingPortal = field(init=False)

    async def __aenter__(self) -> AsyncDataStoreAdapter:
        self._portal = BlockingPortal()
        await self._portal.__aenter__()
        await to_thread.run_sync(self.original.__enter__)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await to_thread.run_sync(self.original.__exit__, exc_type, exc_val, exc_tb)
        await self._portal.__aexit__(exc_type, exc_val, exc_tb)

    async def get_schedules(self, ids: Optional[Set[str]] = None) -> List[Schedule]:
        return await to_thread.run_sync(self.original.get_schedules, ids)

    async def add_schedule(self, schedule: Schedule, conflict_policy: ConflictPolicy) -> None:
        await to_thread.run_sync(self.original.add_schedule, schedule, conflict_policy)

    async def remove_schedules(self, ids: Iterable[str]) -> None:
        await to_thread.run_sync(self.original.remove_schedules, ids)

    @asynccontextmanager
    async def acquire_schedules(self, scheduler_id: str,
                                limit: int) -> AsyncContextManager[List[Schedule], None]:
        cm = self.original.acquire_schedules(scheduler_id, limit)
        schedules = await to_thread.run_sync(cm.__enter__)
        try:
            yield schedules
        except BaseException:
            if not await to_thread.run_sync(cm.__exit__, *sys.exc_info()):
                raise
        else:
            await to_thread.run_sync(cm.__exit__, None, None, None)

    async def add_job(self, job: Job) -> None:
        await to_thread.run_sync(self.original.add_job, job)

    async def get_jobs(self, ids: Optional[Iterable[UUID]] = None) -> List[Job]:
        return await to_thread.run_sync(self.original.get_jobs, ids)

    async def acquire_jobs(self, worker_id: str, limit: Optional[int] = None) -> List[Job]:
        return await to_thread.run_sync(self.original.acquire_jobs, worker_id, limit)

    async def release_job(self, worker_id: str, job_id: UUID, result: Optional[JobResult]) -> None:
        await to_thread.run_sync(self.original.release_job, worker_id, job_id, result)

    async def get_job_result(self, job_id: UUID) -> Optional[JobResult]:
        return await to_thread.run_sync(self.original.get_job_result, job_id)

    def subscribe(self, callback: Callable[[Event], Any],
                  event_types: Optional[Iterable[Type[Event]]] = None) -> SubscriptionToken:
        return self.original.subscribe(partial(self._portal.call, callback), event_types)

    def unsubscribe(self, token: events.SubscriptionToken) -> None:
        self.original.unsubscribe(token)
