"""Resolve: admin operations: departments, members, categories, users."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.models import User, UserRole
from app.repositories import CategoryRepository, DepartmentRepository, UserRepository
from app.schemas import (
    CategoryCreate,
    DepartmentCreate,
    DepartmentMemberAdd,
    DepartmentUpdate,
    PageParams,
    UserAdminUpdate,
)
from app.services.permissions import is_admin, require_admin


class AdminService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.departments = DepartmentRepository(session)
        self.categories = CategoryRepository(session)
        self.users = UserRepository(session)

    async def create_department(self, actor: User, data: DepartmentCreate):
        require_admin(actor)
        if await self.departments.get_by_name(data.name):
            raise ConflictError("A department with this name already exists")
        dept = await self.departments.create(
            name=data.name, description=data.description
        )
        await self.session.commit()
        return dept

    async def update_department(
        self, actor: User, department_id: int, data: DepartmentUpdate
    ):
        require_admin(actor)
        dept = await self.departments.get(department_id)
        if dept is None:
            raise NotFoundError("Department not found")
        changes = data.model_dump(exclude_unset=True)
        new_name = changes.get("name")
        if new_name and new_name.lower() != dept.name.lower():
            if await self.departments.get_by_name(new_name):
                raise ConflictError("A department with this name already exists")
        for field, value in changes.items():
            setattr(dept, field, value)
        await self.session.commit()
        await self.session.refresh(dept)  # onupdate columns are expired
        return dept

    async def add_member(
        self, actor: User, department_id: int, data: DepartmentMemberAdd
    ):
        require_admin(actor)
        if await self.departments.get(department_id) is None:
            raise NotFoundError("Department not found")
        user = await self.users.get(data.user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.role != UserRole.AGENT:
            raise BusinessRuleError("Only users with the 'agent' role can join a department")
        if await self.departments.get_membership(user.id, department_id):
            raise ConflictError("User is already a member of this department")
        member = await self.departments.add_member(
            user_id=user.id, department_id=department_id, member_role=data.member_role
        )
        await self.session.commit()
        await self.session.refresh(member, ["user"])  # needed to serialize in async
        return member

    async def remove_member(self, actor: User, department_id: int, user_id: int):
        require_admin(actor)
        member = await self.departments.get_membership(user_id, department_id)
        if member is None:
            raise NotFoundError("Membership not found")
        await self.departments.remove_member(member)
        await self.session.commit()

    async def create_category(self, actor: User, data: CategoryCreate):
        require_admin(actor)
        if await self.categories.get_by_name(data.name):
            raise ConflictError("A category with this name already exists")
        if data.suggested_department_id is not None:
            if await self.departments.get(data.suggested_department_id) is None:
                raise NotFoundError("Department not found")
        cat = await self.categories.create(
            name=data.name, suggested_department_id=data.suggested_department_id
        )
        await self.session.commit()
        return cat

    async def update_user(self, actor: User, user_id: int, data: UserAdminUpdate):
        require_admin(actor)
        if user_id == actor.id:
            raise BusinessRuleError("You cannot change your own role or status")
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        changes = data.model_dump(exclude_unset=True)
        # A change in privileges or standing must take effect immediately, so any
        # token the user already holds is retired.
        if ("role" in changes and changes["role"] != user.role) or changes.get("is_active") is False:
            user.token_version += 1
        for field, value in changes.items():
            setattr(user, field, value)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def reset_user_mfa(self, actor: User, user_id: int) -> User:
        """For a member of staff who lost their phone AND their recovery codes."""
        require_admin(actor)
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        from app.services.auth_service import AuthService  # avoid an import cycle

        AuthService.clear_mfa(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    # ------------------------------------------------------------------ reads
    async def list_departments(self, actor: User, active_only: bool = False):
        if not is_admin(actor) and actor.role != UserRole.AGENT:
            raise PermissionDeniedError("Staff access required")
        return await self.departments.list(active_only=active_only)

    async def list_department_members(self, actor: User, department_id: int):
        if await self.departments.get(department_id) is None:
            raise NotFoundError("Department not found")
        if not is_admin(actor):
            is_member = actor.role == UserRole.AGENT and await self.departments.is_member(
                actor.id, department_id
            )
            if not is_member:
                raise PermissionDeniedError("You are not a member of this department")
        return await self.departments.list_members(department_id)

    async def list_categories(self):
        """Open to any authenticated user: complainants pick from this."""
        return await self.categories.list()

    async def list_users(
        self,
        actor: User,
        params: PageParams,
        role: UserRole | None = None,
        search: str | None = None,
    ):
        require_admin(actor)
        return await self.users.list(
            role=role, search=search, page=params.page, page_size=params.page_size
        )