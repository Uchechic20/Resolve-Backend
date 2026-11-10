"""Small reusable steps for building tickets in a given state."""


async def file_ticket(client, org, who=None, title="No water in block C"):
    who = who or org.c1
    r = await client.post(
        "/tickets",
        json={
            "title": title,
            "description": "The taps have been dry since Monday morning.",
            "category_id": org.cat_id,
        },
        headers=who.headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def triage(client, org, ticket_id, priority="medium"):
    r = await client.post(
        f"/tickets/{ticket_id}/triage",
        json={"department_id": org.dept_id, "priority": priority},
        headers=org.admin.headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def claim(client, who, ticket_id):
    r = await client.post(f"/tickets/{ticket_id}/claim", headers=who.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def set_status(client, who, ticket_id, status, note=None, expect=200):
    body = {"status": status}
    if note:
        body["resolution_note"] = note
    r = await client.patch(f"/tickets/{ticket_id}/status", json=body, headers=who.headers)
    assert r.status_code == expect, f"{status}: {r.status_code} {r.text}"
    return r.json()


async def ticket_in_state(client, org, state):
    """Return a ticket id moved to: submitted | triaged | assigned |
    in_progress | resolved (assignee is org.a1)."""
    t = await file_ticket(client, org)
    tid = t["id"]
    if state == "submitted":
        return tid
    await triage(client, org, tid)
    if state == "triaged":
        return tid
    await claim(client, org.a1, tid)
    if state == "assigned":
        return tid
    await set_status(client, org.a1, tid, "in_progress")
    if state == "in_progress":
        return tid
    await set_status(client, org.a1, tid, "resolved", note="Pipe replaced and tested.")
    return tid
