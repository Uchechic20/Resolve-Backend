"""Resolve: tamper-evident audit trail.


"""
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Protocol


def compute_event_hash(
    prev_hash: str | None,
    ticket_id: int,
    actor_id: int | None,
    event_type: str,
    from_value: str | None,
    to_value: str | None,
    created_at: datetime,
) -> str:
    stamp = created_at.astimezone(timezone.utc).isoformat()
    material = "|".join(
        [
            prev_hash or "",
            str(ticket_id),
            "" if actor_id is None else str(actor_id),
            event_type,
            from_value or "",
            to_value or "",
            stamp,
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()


class EventLike(Protocol):
    id: int
    ticket_id: int
    actor_id: int | None
    event_type: str
    from_value: str | None
    to_value: str | None
    created_at: datetime
    prev_hash: str | None
    hash: str | None


@dataclass
class Problem:
    ticket_id: int
    event_id: int
    reason: str


@dataclass
class ChainReport:
    checked: int
    problems: list[Problem]
    digest: str  # one hash covering the head of every ticket's chain

    @property
    def ok(self) -> bool:
        return not self.problems


def verify_chain(events: Iterable[EventLike]) -> ChainReport:
    """`events` must be ordered by (ticket_id, id). Rows written before the chain
    existed (hash is None) are skipped; the chain starts at the first hashed row."""
    problems: list[Problem] = []
    heads: dict[int, str] = {}
    last_prev: dict[int, str | None] = {}
    started: set[int] = set()
    checked = 0

    for ev in events:
        tid = ev.ticket_id
        expected_prev = last_prev.get(tid)
        if ev.hash is None:
            if tid in started:
                problems.append(Problem(tid, ev.id, "hash removed from a chained event"))
            continue
        checked += 1
        started.add(tid)
        if ev.prev_hash != expected_prev:
            problems.append(
                Problem(tid, ev.id, "chain broken: an earlier event was removed or reordered")
            )
        recomputed = compute_event_hash(
            ev.prev_hash, tid, ev.actor_id, ev.event_type,
            ev.from_value, ev.to_value, ev.created_at,
        )
        if recomputed != ev.hash:
            problems.append(Problem(tid, ev.id, "event content was modified"))
        last_prev[tid] = ev.hash
        heads[tid] = ev.hash

    digest = hashlib.sha256(
        "\n".join(f"{t}:{h}" for t, h in sorted(heads.items())).encode()
    ).hexdigest()
    return ChainReport(checked=checked, problems=problems, digest=digest)