"""Resolve: admin routes (users, departments, members, categories)."""
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.dependencies import AdminSvc, AdminUser, StaffUser
from app.routers.helpers import page_of
from app.schemas import (
    CategoryCreate,
    CategoryRead,
    DepartmentCreate,
    DepartmentMemberAdd,
    DepartmentMemberRead,
    DepartmentRead,
    DepartmentUpdate,
    Page,
    UserAdminUpdate,
    UserListFilters,
    UserRead,
)


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.get("/users", response_model=Page[UserRead])
async def list_users(
    user: AdminUser, svc: AdminSvc, filters: Annotated[UserListFilters, Query()]
):
    items, total = await svc.list_users(user, filters, filters.role, filters.search)
    return page_of(UserRead, items, total, filters)


@admin_router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int, data: UserAdminUpdate, user: AdminUser, svc: AdminSvc
):
    return await svc.update_user(user, user_id, data)


@admin_router.post("/departments", response_model=DepartmentRead, status_code=201)
async def create_department(data: DepartmentCreate, user: AdminUser, svc: AdminSvc):
    return await svc.create_department(user, data)


@admin_router.patch("/departments/{department_id}", response_model=DepartmentRead)
async def update_department(
    department_id: int, data: DepartmentUpdate, user: AdminUser, svc: AdminSvc
):
    return await svc.update_department(user, department_id, data)


@admin_router.get(
    "/departments/{department_id}/members",
    response_model=list[DepartmentMemberRead],
)
async def list_members(department_id: int, user: StaffUser, svc: AdminSvc):
    return await svc.list_department_members(user, department_id)


@admin_router.post(
    "/departments/{department_id}/members",
    response_model=DepartmentMemberRead,
    status_code=201,
)
async def add_member(
    department_id: int, data: DepartmentMemberAdd, user: AdminUser, svc: AdminSvc
):
    return await svc.add_member(user, department_id, data)


@admin_router.delete(
    "/departments/{department_id}/members/{user_id}", status_code=204
)
async def remove_member(
    department_id: int, user_id: int, user: AdminUser, svc: AdminSvc
):
    await svc.remove_member(user, department_id, user_id)
    return Response(status_code=204)


@admin_router.get("/categories", response_model=list[CategoryRead])
async def list_categories_admin(_: AdminUser, svc: AdminSvc):
    """Includes the suggested-department hint used during triage."""
    return await svc.list_categories()


@admin_router.post("/categories", response_model=CategoryRead, status_code=201)
async def create_category(data: CategoryCreate, user: AdminUser, svc: AdminSvc):
    return await svc.create_category(user, data)
