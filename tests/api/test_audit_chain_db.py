import pytest
import asyncio
from sqlalchemy import text

from app.core.audit_chain import verify_chain
from app.core.database import SessionLocal
from app.repositories import EventRepository
from tests.helpers import file_ticket, ticket_in_state


async def report():
    async with SessionLocal() as s:
        return verify_chain(await EventRepository(s).all_for_verification())


async def test_real_ticket_activity_forms_an_unbroken_chain(client, org):
    tid = await ticket_in_state(client, org, state="resolved")

    # Add a comment to generate more events
    await client.post(f"/tickets/{tid}/comments", json={"body": "hello"}, headers=org.c1.headers)

    async with SessionLocal() as s:
        events = [e for e in await EventRepository(s).all_for_verification() if e.ticket_id == tid]

    assert len(events) >= 6
    assert events[0].prev_hash is None  # The chain starts fresh per ticket

    for before, after in zip(events, events[1:]):
        assert after.prev_hash == before.hash  # Each event points to the one before it

    assert (await report()).ok


async def test_editing_an_old_event_in_the_database_is_detected(client, org):
    t = await file_ticket(client, org)
    tid = t["id"]

    async with SessionLocal() as s:
        row = (await s.execute(text(
            "select id, to_value from ticket_events where ticket_id=:t order by id limit 1"
        ), {"t": tid})).first()

        await s.execute(text("update ticket_events set to_value='FORGED' where id=:i"), {"i": row.id})
        await s.commit()

    try:
        r = await report()
        assert not r.ok
        assert any(p.event_id == row.id and "modified" in p.reason for p in r.problems)
    finally:
        # Put it back so later tests start clean
        async with SessionLocal() as s:
            await s.execute(text("update ticket_events set to_value=:v where id=:i"), {"v": row.to_value, "i": row.id})
            await s.commit()

    assert (await report()).ok


async def test_deleting_a_middle_event_is_detected_and_restored(client, org):
    tid = await ticket_in_state(client, org, state="assigned")

    async with SessionLocal() as s:
        rows = (
            await s.execute(text("select * from ticket_events where ticket_id=:t order by id"), {"t": tid})).fetchall()
        assert len(rows) >= 3
        victim = dict(rows[1]._mapping)  # Convert Row to dict

        await s.execute(text("delete from ticket_events where id=:i"), {"i": victim["id"]})
        await s.commit()

    try:
        r = await report()
        assert not r.ok and any(p.ticket_id == tid for p in r.problems)
    finally:
        # Restore the deleted event.
        # We remove 'id' so the database sequence generates a new one automatically.
        async with SessionLocal() as s:
            restore_data = {k: v for k, v in victim.items() if k != "id"}
            cols = ", ".join(restore_data.keys())
            vals = ", ".join([f":{k}" for k in restore_data.keys()])
            await s.execute(text(f"insert into ticket_events ({cols}) values ({vals})"), restore_data)
            await s.commit()

    assert (await report()).ok


async def test_concurrent_writers_cannot_fork_a_tickets_chain(client, org):
    """Many comments at once on one ticket must still produce a single chain."""
    tid = await ticket_in_state(client, org, state="assigned")

    await asyncio.gather(*[
        client.post(f"/tickets/{tid}/comments", json={"body": f"note {i}"}, headers=org.a1.headers)
        for i in range(8)
    ])

    async with SessionLocal() as s:
        events = [e for e in await EventRepository(s).all_for_verification() if e.ticket_id == tid]

    assert sum(e.event_type == "comment_added" for e in events) == 8
    assert len({e.prev_hash for e in events}) == len(events)  # No two events share a prev_hash
    assert (await report()).ok


async def test_concurrent_uploads_and_comments_do_not_deadlock(client, org):
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 10
    tid = await ticket_in_state(client, org, state="assigned")

    jobs = []
    for i in range(5):
        jobs.append(client.post(f"/tickets/{tid}/comments", json={"body": f"c{i}"}, headers=org.a1.headers))
        jobs.append(client.post(
            f"/tickets/{tid}/attachments",
            files={"file": (f"p{i}.png", png, "image/png")},
            headers=org.a1.headers
        ))

    results = await asyncio.gather(*jobs)
    assert [r.status_code for r in results] == [201] * 10
    assert (await report()).ok