import pytest
from tests.helpers import file_ticket, ticket_in_state
from app.core.config import get_settings

settings = get_settings()
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes" * 10


async def logs(client, admin, **params):
    """Helper to fetch access logs."""
    r = await client.get("/admin/access-logs", params=params, headers=admin.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_every_successful_view_is_recorded_with_who_and_from_where(client, org):
    tid = await ticket_in_state(client, org, state="assigned")

    for who in (org.c1, org.a1, org.admin):
        assert (await client.get(f"/tickets/{tid}", headers=who.headers)).status_code == 200

    body = await logs(client, org.admin, ticket_id=tid, action="view")
    seen = {(e["user_id"], e["detail"]) for e in body["items"]}

    assert seen == {(org.c1.id, "owner"), (org.a1.id, "staff"), (org.admin.id, "staff")}
    assert all(e["ip"] == "127.0.0.1" and e["ticket_id"] == tid for e in body["items"])

    ids = [e["id"] for e in body["items"]]
    assert ids == sorted(ids, reverse=True)  # newest first


async def test_refused_views_leave_no_record(client, org):
    tid = (await file_ticket(client, org, org.c1))["id"]

    # These users should not be able to view the ticket
    assert (await client.get(f"/tickets/{tid}", headers=org.c2.headers)).status_code == 403
    assert (await client.get(f"/tickets/{tid}", headers=org.a1.headers)).status_code == 403

    # Ensure no logs were created for the refused views
    assert (await logs(client, org.admin, ticket_id=tid))["total"] == 0


async def test_downloads_are_recorded_with_the_file_name(client, org):
    tid = (await file_ticket(client, org, org.c1))["id"]

    # Upload an attachment
    att = (await client.post(
        f"/tickets/{tid}/attachments",
        files={"file": ("evidence.png", PNG, "image/png")},
        headers=org.c1.headers
    )).json()

    # Download the attachment
    await client.get(f"/tickets/{tid}/attachments/{att['id']}/download", headers=org.c1.headers)

    # Check the logs
    body = await logs(client, org.admin, ticket_id=tid, action="download")
    assert body["total"] == 1
    assert body["items"][0]["detail"] == "evidence.png"
    assert body["items"][0]["user_id"] == org.c1.id


async def test_filters_and_pagination(client, org):
    tid = (await file_ticket(client, org, org.c1))["id"]

    # Generate 3 views by c1 and 1 view by admin
    for _ in range(3):
        await client.get(f"/tickets/{tid}", headers=org.c1.headers)
    await client.get(f"/tickets/{tid}", headers=org.admin.headers)

    # Test filtering by user_id
    assert (await logs(client, org.admin, ticket_id=tid, user_id=org.c1.id))["total"] == 3
    assert (await logs(client, org.admin, ticket_id=tid, user_id=org.admin.id))["total"] == 1

    # Test pagination
    page = await logs(client, org.admin, ticket_id=tid, page=2, page_size=3)
    assert page["total"] == 4
    assert len(page["items"]) == 1
    assert page["page"] == 2

    # Test max page size validation
    r = await client.get("/admin/access-logs", params={"page_size": 500}, headers=org.admin.headers)
    assert r.status_code == 422


async def test_only_admins_can_read_the_log(client, org):
    # Non-admin users (c1, a1, head) should get 403 Forbidden
    for who in (org.c1, org.a1, org.head):
        assert (await client.get("/admin/access-logs", headers=who.headers)).status_code == 403

    # Unauthenticated requests should get 401 Unauthorized
    assert (await client.get("/admin/access-logs")).status_code == 401