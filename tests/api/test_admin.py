import uuid
import pytest


def tag():
    return uuid.uuid4().hex[:8]


async def test_only_admins_manage_departments(client, org):
    body = {"name": f"Library-{tag()}"}

    for who in (org.c1, org.a1, org.head):
        assert (await client.post("/admin/departments", json=body, headers=who.headers)).status_code == 403

    assert (await client.post("/admin/departments", json=body)).status_code == 401
    assert (await client.post("/admin/departments", json=body, headers=org.admin.headers)).status_code == 201


async def test_department_names_are_unique_ignoring_case(client, org):
    name = f"Security-{tag()}"
    assert (await client.post("/admin/departments", json={"name": name}, headers=org.admin.headers)).status_code == 201

    r = await client.post("/admin/departments", json={"name": name.upper()}, headers=org.admin.headers)
    assert r.status_code == 409


async def test_update_department_and_rename_conflicts(client, org):
    # Update description
    r = await client.patch(
        f"/admin/departments/{org.dept_id}",
        json={"description": "Hostel affairs"},
        headers=org.admin.headers
    )
    assert r.status_code == 200 and r.json()["description"] == "Hostel affairs"

    # Rename to an existing name should conflict
    other = (await client.get("/departments", headers=org.admin.headers)).json()
    other_name = next(d["name"] for d in other if d["id"] == org.other_dept_id)

    r = await client.patch(
        f"/admin/departments/{org.dept_id}",
        json={"name": other_name},
        headers=org.admin.headers
    )
    assert r.status_code == 409

    # 404 for non-existent department
    assert (await client.patch("/admin/departments/999999", json={"name": "x" * 3},
                               headers=org.admin.headers)).status_code == 404


async def test_department_list_is_for_staff_and_can_hide_inactive(client, org):
    assert (await client.get("/departments", headers=org.c1.headers)).status_code == 403

    await client.patch(
        f"/admin/departments/{org.other_dept_id}",
        json={"is_active": False},
        headers=org.admin.headers
    )

    active = (await client.get("/departments", params={"active_only": True}, headers=org.a1.headers)).json()
    ids = [d["id"] for d in active]
    assert org.dept_id in ids and org.other_dept_id not in ids


async def test_membership_rules(client, org, make_user):
    path = f"/admin/departments/{org.dept_id}/members"
    newbie = await make_user("agent")

    # Add new member (201 Created)
    r = await client.post(path, json={"user_id": newbie.id, "member_role": "head"}, headers=org.admin.headers)
    assert r.status_code == 201 and r.json()["member_role"] == "head" and "user" in r.json()

    # Already a member (409 Conflict)
    r = await client.post(path, json={"user_id": newbie.id}, headers=org.admin.headers)
    assert r.status_code == 409

    # Complainants cannot join departments (422 Unprocessable)
    r = await client.post(path, json={"user_id": org.c1.id}, headers=org.admin.headers)
    assert r.status_code == 422

    # Non-existent user (404 Not Found)
    r = await client.post(path, json={"user_id": 999999}, headers=org.admin.headers)
    assert r.status_code == 404

    # Non-existent department (404 Not Found)
    r = await client.post("/admin/departments/999999/members", json={"user_id": newbie.id}, headers=org.admin.headers)
    assert r.status_code == 404

    # Unauthorized user trying to add (403 Forbidden)
    assert (await client.post(path, json={"user_id": newbie.id}, headers=org.head.headers)).status_code == 403


async def test_listing_and_removing_members(client, org):
    path = f"/admin/departments/{org.dept_id}/members"
    members = (await client.get(path, headers=org.a1.headers)).json()

    assert {m["user"]["id"] for m in members} == {org.head.id, org.a1.id, org.a2.id}
    assert (await client.get(path, headers=org.outsider.headers)).status_code == 403
    assert (await client.get(path, headers=org.c1.headers)).status_code == 403

    # Remove a member
    assert (await client.delete(f"{path}/{org.a2.id}", headers=org.admin.headers)).status_code == 204
    # Try to remove again (404 Not Found)
    assert (await client.delete(f"{path}/{org.a2.id}", headers=org.admin.headers)).status_code == 404


async def test_categories(client, org):
    name = f"Noise-{tag()}"

    # Create category
    r = await client.post(
        "/admin/categories",
        json={"name": name, "suggested_department_id": org.dept_id},
        headers=org.admin.headers
    )
    assert r.status_code == 201 and r.json()["suggested_department_id"] == org.dept_id

    # Duplicate name (case-insensitive) conflict
    assert (await client.post("/admin/categories", json={"name": name.lower()},
                              headers=org.admin.headers)).status_code == 409

    # Suggested department does not exist (404)
    r = await client.post("/admin/categories", json={"name": f"x-{tag()}", "suggested_department_id": 999999},
                          headers=org.admin.headers)
    assert r.status_code == 404

    # Missing suggested department id (422)
    assert (await client.post("/admin/categories", json={"name": f"y-{tag()}"},
                              headers=org.admin.headers)).status_code == 422

    # Complainants can list categories, but without the internal routing hint
    public = (await client.get("/categories", headers=org.c1.headers)).json()
    assert name in [c["name"] for c in public]
    assert all("suggested_department_id" not in c for c in public)

    # Unauthenticated access (401)
    assert (await client.get("/categories")).status_code == 401

    # Staff can see the hint
    staff = (await client.get("/admin/categories", headers=org.admin.headers)).json()
    assert any(c["name"] == name and c["suggested_department_id"] == org.dept_id for c in staff)


async def test_user_management(client, org, make_user):
    target = await make_user()

    # Update role
    r = await client.patch(f"/admin/users/{target.id}", json={"role": "agent"}, headers=org.admin.headers)
    assert r.status_code == 200 and r.json()["role"] == "agent"

    # Invalid role (422)
    r = await client.patch(f"/admin/users/{target.id}", json={"role": "boss"}, headers=org.admin.headers)
    assert r.status_code == 422

    # Non-existent user (404)
    assert (await client.patch("/admin/users/999999", json={"role": "agent"},
                               headers=org.admin.headers)).status_code == 404

    # Nobody changes their own role or status (422)
    r = await client.patch(f"/admin/users/{org.admin.id}", json={"role": "complainant"}, headers=org.admin.headers)
    assert r.status_code == 422

    # Unauthorized user trying to change role (403)
    assert (await client.patch(f"/admin/users/{target.id}", json={"role": "admin"},
                               headers=org.c1.headers)).status_code == 403


async def test_user_listing_is_admin_only_and_filterable(client, org):
    assert (await client.get("/admin/users", headers=org.a1.headers)).status_code == 403

    r = await client.get("/admin/users", params={"role": "admin", "page_size": 5}, headers=org.admin.headers)
    assert r.status_code == 200

    body = r.json()
    assert body["total"] >= 1 and all(u["role"] == "admin" for u in body["items"])
    # Ensure sensitive data is not leaked
    assert all("password" not in u and "password_hash" not in u for u in body["items"])

    # Search by email
    r = await client.get("/admin/users", params={"search": org.c1.email}, headers=org.admin.headers)
    assert [u["id"] for u in r.json()["items"]] == [org.c1.id]