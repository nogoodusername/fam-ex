from typing import Optional
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.household import Household, HouseholdMember


class HouseholdRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, household_id: int) -> Optional[Household]:
        result = await self.db.execute(
            select(Household)
            .options(selectinload(Household.members).selectinload(HouseholdMember.user))
            .where(Household.id == household_id)
        )
        return result.scalar_one_or_none()

    async def create(self, *, name: str, currency: str, language: str, cycle_start_day: int) -> Household:
        household = Household(
            name=name, currency=currency, language=language, cycle_start_day=cycle_start_day
        )
        self.db.add(household)
        await self.db.flush()
        await self.db.refresh(household)
        return household

    async def update(self, household: Household, **fields) -> Household:
        for key, value in fields.items():
            if value is not None:
                setattr(household, key, value)
        await self.db.flush()
        await self.db.refresh(household)
        return household

    async def try_reserve_member_slot(self, household_id: int, cap: int) -> bool:
        """Atomically claim one of the household's member slots, if any remain.

        A single conditional UPDATE, not a count-then-insert — two concurrent joins
        against a household with one slot left can't both read "count < cap" as true
        and both proceed, since only one UPDATE can match the WHERE clause and win.
        """
        result = await self.db.execute(
            sql_update(Household)
            .where(Household.id == household_id, Household.member_count < cap)
            .values(member_count=Household.member_count + 1)
        )
        return result.rowcount == 1

    async def release_member_slot(self, household_id: int) -> None:
        await self.db.execute(
            sql_update(Household)
            .where(Household.id == household_id)
            .values(member_count=Household.member_count - 1)
        )

    async def delete(self, household: Household) -> None:
        """Cascades to members/budgets/categories/transactions/invites via the ORM
        `cascade="all, delete-orphan"` relationships on Household — see account
        deletion's sole-member-household path in HouseholdService.
        """
        await self.db.delete(household)
        await self.db.flush()
