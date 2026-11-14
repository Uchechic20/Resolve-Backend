import re
import pytest

# Import the specific helper functions you need directly
from tests import helpers


async def test_filing_returns_the_complainant_view(client, org):
    t = await helpers.file_ticket(client, org)

    assert re.fullmatch(r"RSV-\d{4}-\d{5}", t["reference"])
    assert t["status"] == "submitted"

    # routing and staff details are internal
    for hidden in ("assignee", "events", "department", "complainant"):
        assert hidden not in t


async def test_references_are_unique_and_increasing(client, org):
    a = await helpers.file_ticket(client, org)
    b = await helpers.file_ticket(client, org)

    num = lambda t: int(t["reference"].rsplit("-", 1)[1])
    assert num(b) > num(a)


async def test_filing_validation(client, org):
    ok = {"title": "Broken window", "description": "Window in room 12 is cracked.", "category_id": 1}

    # Title too short
    r = await client.post("/tickets", json={**ok, "title": "abc"}, headers=org.c1.headers)
    assert r.status_code == 422

    # Non-existent category
    r = await client.post("/tickets", json={**ok, "category_id": 999999}, headers=org.c1.headers)
    assert r.status_code == 404

    # Unauthenticated
    r = await client.post("/tickets", json=ok)
    assert r.status_code == 401


async def test_complainants_see_only_their_own_tickets(client, org):
    mine = await helpers.file_ticket(client, org, org.c1)
    theirs = await helpers.file_ticket(client, org, org.c2)

    listing = (await client.get("/tickets/mine", headers=org.c1.headers)).json()
    ids = [t["id"] for t in listing["items"]]

    assert mine["id"] in ids and theirs["id"] not in ids

    # Someone else's ticket looks like it does not exist (no ID probing)
    assert (await client.get(f"/tickets/{theirs['id']}", headers=org.c1.headers)).status_code == 404
    assert (await client.get("/tickets/999999999", headers=org.c1.headers)).status_code == 404


async def test_my_tickets_pagination_and_status_filter(client, org):
    for _ in range(3):
        await helpers.file_ticket(client, org, org.c2)

    page = (await client.get("/tickets/mine", params={"page": 1, "page_size": 2}, headers=org.c2.headers)).json()
    assert len(page["items"]) == 2 and page["total"] == 3 and page["page_size"] == 2

    none = (await client.get("/tickets/mine", params={"status": "closed"}, headers=org.c2.headers)).json()
    assert none["total"] == 0

    # Max page size validation
    assert (await client.get("/tickets/mine", params={"page_size": 500}, headers=org.c2.headers)).status_code == 422


async def in_intake(client, org, ticket_id) -> bool:
    """Intake lists oldest first, so a new ticket may be on a later page."""
    page = 1
    while True:
        r = await client.get("/tickets/intake", params={"page": page, "page_size": 100}, headers=org.admin.headers)
        assert r.status_code == 200
        body = r.json()

        if ticket_id in [x["id"] for x in body["items"]]:
            return True

        if page * 100 >= body["total"]:
            return False

        page += 1


async def test_intake_is_admin_only(client, org):
    t = await helpers.file_ticket(client, org)

    assert (await client.get("/tickets/intake", headers=org.c1.headers)).status_code == 403
    assert (await client.get("/tickets/intake", headers=org.a1.headers)).status_code == 403
    assert await in_intake(client, org, t["id"])

    # Agents cannot even open an un-routed ticket...
    assert (await client.get(f"/tickets/{t['id']}", headers=org.a1.headers)).status_code == 404

    # ...until it is routed to their department, which also takes it out of intake
    await helpers.triage(client, org, t["id"])
    assert not await in_intake(client, org, t["id"])
    assert (await client.get(f"/tickets/{t['id']}", headers=org.a1.headers)).status_code == 200


async def test_full_lifecycle_with_audit_trail(client, org):
    t = await helpers.file_ticket(client, org)
    tid = t["id"]

    await helpers.triage(client, org, tid, priority="high")
    await helpers.claim(client, org.a1, tid)
    await helpers.set_status(client, org.a1, tid, status="in_progress")

    resolved = await helpers.set_status(client, org.a1, tid, status="resolved", note="Pipe replaced.")
    assert resolved["resolution_note"] == "Pipe replaced."

    closed = await helpers.set_status(client, org.a1, tid, status="closed")
    assert closed["status"] == "closed"

    staff = (await client.get(f"/tickets/{tid}", headers=org.admin.headers)).json()
    assert staff["priority"] == "high" and staff["assignee"]["id"] == org.a1.id
    assert staff["department"]["id"] == org.dept_id

    # the complainant sees the outcome but none of the internals
    pub = (await client.get(f"/tickets/{tid}", headers=org.c1.headers)).json()
    assert pub["status"] == "closed" and pub["resolution_note"] == "Pipe replaced."
    assert "events" not in pub and "assignee" not in pub


async def test_illegal_transitions_are_409(client, org):
    submitted = await helpers.ticket_in_state(client, org, state="submitted")
    r = await client.patch(f"/tickets/{submitted}/status", json={"status": "in_progress"}, headers=org.a1.headers)
    assert r.status_code == 409

    assigned = await helpers.ticket_in_state(client, org, state="assigned")
    r = await client.patch(
        f"/tickets/{assigned}/status",
        json={"status": "resolved", "resolution_note": "Skipping a step."},
        headers=org.a1.headers
    )
    assert r.status_code == 409  # must go through in_progress first

    inprog = await helpers.ticket_in_state(client, org, state="in_progress")
    await helpers.set_status(client, org.a1, inprog, status="in_progress", expect=409)  # no-op change


async def test_status_endpoint_refuses_states_with_their_own_actions(client, org):
    tid = await helpers.ticket_in_state(client, org, state="in_progress")

    for status in ("triaged", "assigned", "submitted", "rejected", "reopened"):
        r = await client.patch(f"/tickets/{tid}/status", json={"status": status}, headers=org.a1.headers)
        assert r.status_code == 422, status


async def test_resolving_needs_a_note(client, org):
    tid = await helpers.ticket_in_state(client, org, state="in_progress")
    r = await client.patch(f"/tickets/{tid}/status", json={"status": "resolved"}, headers=org.a1.headers)
    assert r.status_code == 422


async def test_only_assignee_head_or_admin_can_update_status(client, org):
    tid = await helpers.ticket_in_state(client, org, state="assigned")

    await helpers.set_status(client, org.a2, tid, status="in_progress", expect=403)  # colleague, not assignee
    await helpers.set_status(client, org.outsider, tid, status="in_progress", expect=404)  # other department
    await helpers.set_status(client, org.head, tid, status="in_progress")  # head can


async def test_closed_tickets_are_final(client, org):
    tid = await helpers.ticket_in_state(client, org, state="resolved")
    await helpers.set_status(client, org.a1, tid, status="closed")

    r = await client.post(f"/tickets/{tid}/reopen", json={"reason": "Still broken"}, headers=org.c1.headers)
    assert r.status_code == 409

    r = await client.post(f"/tickets/{tid}/comments", json={"body": "hello?"}, headers=org.c1.headers)
    assert r.status_code == 409

    await helpers.set_status(client, org.a1, tid, status="in_progress", expect=409)


async def test_reopen_sends_the_ticket_back_to_its_assignee(client, org):
    tid = await helpers.ticket_in_state(client, org, state="resolved")

    r = await client.post(f"/tickets/{tid}/reopen", json={"reason": "Water is gone again"}, headers=org.c2.headers)
    assert r.status_code == 404  # not the owner

    r = await client.post(f"/tickets/{tid}/reopen", json={"reason": "Water is gone again"}, headers=org.c1.headers)
    assert r.status_code == 200

    body = r.json()
    assert body["status"] == "reopened" and body["resolved_at"] is None
    assert any("Water is gone again" in c["body"] for c in body["comments"])

    await helpers.set_status(client, org.a1, tid, status="in_progress")  # same assignee carries on


async def test_only_resolved_tickets_can_be_reopened(client, org):
    tid = await helpers.ticket_in_state(client, org, state="in_progress")
    r = await client.post(f"/tickets/{tid}/reopen", json={"reason": "Not fixed yet"}, headers=org.c1.headers)
    assert r.status_code == 409


async def test_triage_routes_and_can_adjust_priority_and_category(client, org):
    t = await helpers.file_ticket(client, org)
    r = await client.post(
        f"/tickets/{t['id']}/triage",
        json={"department_id": org.dept_id, "priority": "urgent", "category_id": org.cat_id},
        headers=org.admin.headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "triaged" and body["priority"] == "urgent"
    assert body["department"]["id"] == org.dept_id


async def test_triage_rules(client, org):
    t = await helpers.file_ticket(client, org)
    tid = t["id"]

    # Admin only
    r = await client.post(f"/tickets/{tid}/triage", json={"department_id": org.dept_id}, headers=org.a1.headers)
    assert r.status_code == 403

    # Non-existent department
    r = await client.post(f"/tickets/{tid}/triage", json={"department_id": 999999}, headers=org.admin.headers)
    assert r.status_code == 404

    # Inactive department
    await client.patch(f"/admin/departments/{org.other_dept_id}", json={"is_active": False}, headers=org.admin.headers)
    r = await client.post(f"/tickets/{tid}/triage", json={"department_id": org.other_dept_id},
                          headers=org.admin.headers)
    assert r.status_code == 422  # inactive department

    # Already triaged
    await helpers.triage(client, org, tid)
    r = await client.post(f"/tickets/{tid}/triage", json={"department_id": org.dept_id}, headers=org.admin.headers)
    assert r.status_code == 409


async def test_rejecting_at_triage_shows_the_reason_to_the_complainant(client, org):
    t = await helpers.file_ticket(client, org)

    r = await client.post(
        f"/tickets/{t['id']}/triage",
        json={"reject": True, "rejection_reason": "Duplicate of an existing complaint"},
        headers=org.admin.headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"

    pub = (await client.get(f"/tickets/{t['id']}", headers=org.c1.headers)).json()
    assert pub["resolution_note"] == "Duplicate of an existing complaint"

    # Cannot comment on a rejected ticket
    r = await client.post(f"/tickets/{t['id']}/comments", json={"body": "why?"}, headers=org.c1.headers)
    assert r.status_code == 409
    print(type(helpers.file_ticket))