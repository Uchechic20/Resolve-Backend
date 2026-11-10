import os
import pytest
from app.core.config import settings
from tests.helpers import file_ticket, set_status, ticket_in_state

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes" * 10
PDF = b"%PDF-1.7\n" + b"fake-pdf-bytes" * 10


def files_on_disk() -> int:
    return len(os.listdir(settings.upload_dir)) if os.path.isdir(settings.upload_dir) else 0


async def upload(client, who, tid, name: str = "photo.png", data: bytes = PNG, mime: str = "image/png"):
    return await client.post(
        f"/tickets/{tid}/attachments",
        files={"file": (name, data, mime)},
        headers=who.headers
    )


async def test_complainant_uploads_and_it_shows_on_the_ticket(client, org):
    tid = (await file_ticket(client, org))["id"]
    before = files_on_disk()

    r = await upload(client, org.c1, tid)
    assert r.status_code == 201

    body = r.json()
    assert body["content_type"] == "image/png" and body["size_bytes"] == len(PNG)
    assert files_on_disk() == before + 1

    detail = (await client.get(f"/tickets/{tid}", headers=org.c1.headers)).json()
    assert [a["id"] for a in detail["attachments"]] == [body["id"]]


async def test_pdf_is_accepted_and_type_comes_from_the_bytes(client, org):
    tid = (await file_ticket(client, org))["id"]

    # Upload a PDF but lie about the MIME type (say it's a png)
    r = await upload(client, org.c1, tid, name="scan.png", data=PDF, mime="image/png")

    # Backend should sniff the bytes and override the mime type to application/pdf
    assert r.status_code == 201 and r.json()["content_type"] == "application/pdf"


async def test_disguised_and_unsupported_files_are_refused(client, org):
    tid = (await file_ticket(client, org))["id"]
    before = files_on_disk()

    for name, data in [
        ("photo.png", b"MZ\x90\x00 this is really an exe"),
        ("page.png", b"<html><script>alert(1)</script></html>"),
        ("empty.png", b""),
        ("anim.gif", b"GIF89a" + b"x" * 20),
    ]:
        r = await upload(client, org.c1, tid, name=name, data=data)
        assert r.status_code == 415, name

    assert files_on_disk() == before


async def test_path_tricks_in_filenames_are_neutralised(client, org):
    tid = (await file_ticket(client, org))["id"]
    r = await upload(client, org.c1, tid, name="../../etc/evil.png")

    assert r.status_code == 201 and r.json()["filename"] == "evil.png"
    # Ensure no path traversal occurred on the disk
    assert all(n.count(".") <= 1 and "/" not in n for n in os.listdir(settings.upload_dir))


async def test_oversize_upload_is_refused_and_leaves_nothing_behind(client, org):
    tid = (await file_ticket(client, org))["id"]
    before = files_on_disk()

    # Create a payload larger than the max allowed size
    r = await upload(client, org.c1, tid, data=PNG + b"0" * (settings.max_upload_bytes + 10))
    assert r.status_code == 413
    assert files_on_disk() == before


async def test_attachment_count_limit(client, org):
    tid = (await file_ticket(client, org))["id"]

    # Upload up to the max limit
    for i in range(settings.max_attachments_per_ticket):
        assert (await upload(client, org.c1, tid, name=f"p{i}.png")).status_code == 201

    # The next one should fail
    r = await upload(client, org.c1, tid, name="one-too-many.png")
    assert r.status_code == 422


async def test_who_may_upload(client, org):
    intake = (await file_ticket(client, org))["id"]

    # Outsiders and other complainants cannot upload to an intake ticket
    assert (await upload(client, org.c2, intake)).status_code == 404
    assert (await upload(client, org.a1, intake)).status_code == 404

    # Admin can upload
    assert (await upload(client, org.admin, intake)).status_code == 201

    # Once assigned, staff can add evidence
    assigned = await ticket_in_state(client, org, state="assigned")
    assert (await upload(client, org.a1, assigned)).status_code == 201

    # Outsiders still cannot upload
    assert (await upload(client, org.outsider, assigned)).status_code == 404

    # No file sent in request
    r = await client.post(f"/tickets/{assigned}/attachments", headers=org.c1.headers)
    assert r.status_code == 422


async def test_download_access_and_safe_headers(client, org):
    tid = await ticket_in_state(client, org, state="assigned")
    att = (await upload(client, org.c1, tid)).json()
    url = f"/tickets/{tid}/attachments/{att['id']}/download"

    # Allowed users can download
    for who in (org.c1, org.a1, org.admin):
        r = await client.get(url, headers=who.headers)
        assert r.status_code == 200 and r.content == PNG

    # Verify security headers prevent the browser from rendering the file inline
    r = await client.get(url, headers=org.a1.headers)
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"

    # Unauthorized users get 404 (to prevent enumeration) or 401
    for stranger in (org.c2, org.outsider):
        assert (await client.get(url, headers=stranger.headers)).status_code == 404
    assert (await client.get(url)).status_code == 401


async def test_attachment_must_belong_to_the_ticket_in_the_url(client, org):
    mine = (await file_ticket(client, org, org.c1))["id"]
    theirs = (await file_ticket(client, org, org.c2))["id"]

    att = (await upload(client, org.c2, theirs)).json()

    # c1 owns 'mine', but the attachment is on c2's ticket: no cross-ticket reads
    r = await client.get(f"/tickets/{mine}/attachments/{att['id']}/download", headers=org.c1.headers)
    assert r.status_code == 404


async def test_delete_rules(client, org):
    tid = await ticket_in_state(client, org, state="assigned")
    att = (await upload(client, org.c1, tid)).json()
    url = f"/tickets/{tid}/attachments/{att['id']}"
    before = files_on_disk()

    # Staff and other users cannot delete
    assert (await client.delete(url, headers=org.a1.headers)).status_code == 403
    assert (await client.delete(url, headers=org.c2.headers)).status_code == 404

    # Uploader can delete
    assert (await client.delete(url, headers=org.c1.headers)).status_code == 204
    assert files_on_disk() == before - 1

    # Ensure it's gone
    assert (await client.get(f"{url}/download", headers=org.c1.headers)).status_code == 404

    # Admin can remove anyone's file
    again = (await upload(client, org.c1, tid)).json()
    assert (await client.delete(f"/tickets/{tid}/attachments/{again['id']}",
                                headers=org.admin.headers)).status_code == 204


async def test_closed_tickets_take_no_attachment_changes(client, org):
    tid = await ticket_in_state(client, org, state="in_progress")
    att = (await upload(client, org.c1, tid)).json()

    # Advance the ticket to closed
    await set_status(client, org.a1, tid, state="resolved", note="Done and dusted.")
    await set_status(client, org.a1, tid, state="closed")

    # Cannot add new attachments
    assert (await upload(client, org.c1, tid)).status_code == 409
    # Cannot delete existing attachments
    assert (await client.delete(f"/tickets/{tid}/attachments/{att['id']}", headers=org.c1.headers)).status_code == 409


async def test_uploads_are_recorded_in_the_audit_trail(client, org):
    tid = (await file_ticket(client, org))["id"]
    att = (await upload(client, org.c1, tid)).json()

    await client.delete(f"/tickets/{tid}/attachments/{att['id']}", headers=org.c1.headers)

    events = (await client.get(f"/tickets/{tid}", headers=org.admin.headers)).json()["events"]
    types = [e["event_type"] for e in events]

    assert types == ["created", "attachment_added", "attachment_removed"]