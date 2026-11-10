"""The tamper-evident audit trail, checked against real database rows."""
from sqlalchemy import text

from app.core.audit_chain import verify_chain
from app.core.database import SessionLocal
from app.repositories import EventRepository
from tests.helpers import file_ticket, ticket_in_state


async def report():
    async with SessionLocal() as s:
        return verify_chain(await EventRepository(s).all_for_verification())


async def test_real_ticket_activity_forms_an_unbroken_chain(client, org):
    tid = await ticket_in_state(client, org, "resolved")
    await client.post(f"/tickets/{tid}/comments", json={"body": "hello"}, headers=org.c1.headers)
    async with SessionLocal() as s:
        events = [e for e in await EventRepository(s).all_for_verification() if e.ticket_id == tid]
    assert len(events) >= 6
    assert events[0].prev_hash is None                       # the chain starts fresh per ticket
    for before, after in zip(events, events[1:]):
        assert after.prev_hash == before.hash                # each event points at the one before
    assert (await report()).ok


async def test_editing_an_old_event_in_the_database_is_detected(client, org):
    t = await file_ticket(client, org)
    tid = t["id"]
    async with SessionLocal() as s:
        row = (await s.execute(text(
            "select id, to_value from ticket_events where ticket_id=:t order by id limit 1"), {"t": tid})).one()
        await s.execute(text("update ticket_events set to_value='FORGED' where id=:i"), {"i": row.id})
        await s.commit()
    try:
        r = await report()
        assert not r.ok
        assert any(p.event_id == row.id and "modified" in p.reason for p in r.problems)
    finally:
        async with SessionLocal() as s:  # put it back so later tests start clean
            await s.execute(text("update ticket_events set to_value=:v where id=:i"), {"v": row.to_value, "i": row.id})
            await s.commit()
    assert (await report()).ok


async def test_deleting_a_middle_event_is_detected_and_restored(client, org):
    tid = await ticket_in_state(client, org, "assigned")
    async with SessionLocal() as s:
        rows = (await s.execute(text("select * from ticket_events where ticket_id=:t order by id"), {"t": tid})).mappings().all()
        victim = dict(rows[1])
        await s.execute(text("delete from ticket_events where id=:i"), {"i": victim["id"]})
        await s.commit()
    try:
        r = await report()
        assert not r.ok and any(p.ticket_id == tid for p in r.problems)
    finally:
        async with SessionLocal() as s:
            cols = ", ".join(victim)
            await s.execute(text(f"insert into ticket_events ({cols}) values ({', '.join(':' + c for c in victim)})"), victim)
            await s.commit()
    assert (await report()).ok


async def test_concurrent_writers_cannot_fork_a_tickets_chain(client, org):
    """Many comments at once on one ticket must still produce a single chain."""
    import asyncio

    tid = await ticket_in_state(client, org, "assigned")
    await asyncio.gather(*[
        client.post(f"/tickets/{tid}/comments", json={"body": f"note {i}"}, headers=org.a1.headers)
        for i in range(8)
    ])
    async with SessionLocal() as s:
        events = [e for e in await EventRepository(s).all_for_verification() if e.ticket_id == tid]
    assert sum(e.event_type == "comment_added" for e in events) == 8
    assert len({e.prev_hash for e in events}) == len(events)  # no two events share a predecessor
    assert (await report()).ok


async def test_concurrent_uploads_and_comments_do_not_deadlock(client, org):
    import asyncio

    png = b"\x89PNG\r\n\x1a\n" + b"x" * 40
    tid = await ticket_in_state(client, org, "assigned")
    jobs = [client.post(f"/tickets/{tid}/comments", json={"body": f"c{i}"}, headers=org.a1.headers) for i in range(4)]
    jobs += [client.post(f"/tickets/{tid}/attachments", files={"file": (f"p{i}.png", png, "image/png")},
                         headers=org.c1.headers) for i in range(3)]
    results = await asyncio.gather(*jobs)
    assert [r.status_code for r in results] == [201] * 7
    assert (await report()).ok