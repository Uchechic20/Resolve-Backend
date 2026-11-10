"""Resolve: department and category read routes."""
from fastapi import APIRouter

from app.dependencies import AdminSvc, CurrentUser, StaffUser, TicketSvc
from app.routers.helpers import Pagination, page_of
from app.schemas import CategoryPublic, DepartmentRead, Page, TicketStaffSummary


departments_router = APIRouter(prefix="/departments", tags=["departments"])


@departments_router.get("", response_model=list[DepartmentRead])
async def list_departments(
    user: StaffUser, svc: AdminSvc, active_only: bool = False
):
    return await svc.list_departments(user, active_only)


@departments_router.get(
    "/{department_id}/queue", response_model=Page[TicketStaffSummary]
)
async def department_queue(
    department_id: int, user: StaffUser, svc: TicketSvc, params: Pagination
):
    """Triaged, unclaimed tickets waiting in this department."""
    items, total = await svc.list_department_queue(user, department_id, params)
    return page_of(TicketStaffSummary, items, total, params)


categories_router = APIRouter(prefix="/categories", tags=["categories"])


@categories_router.get("", response_model=list[CategoryPublic])
async def list_categories(_: CurrentUser, svc: AdminSvc):
    """What complainants choose from when filing."""
    return await svc.list_categories()
