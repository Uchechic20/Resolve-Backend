"""Resolve: API routers.

Routers are thin: parse the request, call ONE service method, shape the
response. No business rules, no queries.

Needs FastAPI >= 0.115 (query parameter models via Query()).
"""
from app.routers.admin import admin_router
from app.routers.attachments import attachments_router
from app.routers.auth import auth_router
from app.routers.departments import categories_router, departments_router
from app.routers.tickets import tickets_router

all_routers = [
    auth_router,
    tickets_router,
    attachments_router,
    departments_router,
    categories_router,
    admin_router,
]

__all__ = ["all_routers"]
