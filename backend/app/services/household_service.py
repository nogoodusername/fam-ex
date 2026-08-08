from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import HOUSEHOLD_MEMBER_CAP, INVITE_EXPIRY_DAYS
from app.core.email import send_invite_email
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationAppError,
)
from app.core.security import generate_invite_token
from app.models.household import Household, HouseholdMember, MemberRole
from app.models.invite import Invite
from app.models.user import User
from app.repositories.household_member_repository import HouseholdMemberRepository
from app.repositories.household_repository import HouseholdRepository
from app.repositories.invite_repository import InviteRepository
from app.schemas.household import HouseholdCreate, HouseholdUpdate, InviteCreate


class HouseholdService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.households = HouseholdRepository(db)
        self.members = HouseholdMemberRepository(db)
        self.invites = InviteRepository(db)

    async def _add_member_or_raise(
        self, household_id: int, user_id: int, role: MemberRole
    ) -> HouseholdMember:
        """Shared by create_household/join_household: reserve a member slot and
        insert the membership, translating either guard's failure into the same
        ConflictError a check-then-act read would have raised.
        """
        if not await self.households.try_reserve_member_slot(household_id, HOUSEHOLD_MEMBER_CAP):
            raise ConflictError(
                f"Household already has the maximum of {HOUSEHOLD_MEMBER_CAP} members"
            )
        try:
            return await self.members.create(household_id=household_id, user_id=user_id, role=role)
        except IntegrityError as exc:
            # The caller's get_by_user check is a fast-path — a concurrent request can
            # still slip past it before either commits. household_members.user_id has
            # a unique constraint as the real guard, so a race lands here instead.
            raise ConflictError(
                "You already belong to a household — v1 supports only one per user"
            ) from exc

    async def create_household(self, user: User, payload: HouseholdCreate) -> Household:
        existing_membership = await self.members.get_by_user(user.id)
        if existing_membership is not None:
            raise ConflictError("You already belong to a household — v1 supports only one per user")

        household = await self.households.create(
            name=payload.name,
            currency=payload.currency,
            language=payload.language,
            cycle_start_day=payload.cycle_start_day,
        )
        await self._add_member_or_raise(household.id, user.id, MemberRole.OWNER)
        return await self.households.get_by_id(household.id)

    async def get_household_or_404(self, household_id: int) -> Household:
        household = await self.households.get_by_id(household_id)
        if household is None:
            raise NotFoundError("Household not found")
        return household

    async def update_household(self, household: Household, payload: HouseholdUpdate) -> Household:
        return await self.households.update(
            household,
            name=payload.name,
            currency=payload.currency,
            language=payload.language,
            cycle_start_day=payload.cycle_start_day,
        )

    async def create_invite(
        self, household: Household, invited_by: User, payload: InviteCreate
    ) -> Invite:
        # A friendly pre-check only — it saves generating a useless invite, but the
        # cap is actually enforced atomically at join time (see _add_member_or_raise),
        # since another invite could still fill the last slot before this one is used.
        if household.member_count >= HOUSEHOLD_MEMBER_CAP:
            raise ConflictError(
                f"Household already has the maximum of {HOUSEHOLD_MEMBER_CAP} members"
            )

        invite = await self.invites.create(
            household_id=household.id,
            invited_by_id=invited_by.id,
            email=payload.email,
            token=generate_invite_token(),
            expires_at=datetime.utcnow() + timedelta(days=INVITE_EXPIRY_DAYS),
        )
        if payload.email:
            await send_invite_email(payload.email, household.name, invite.token)
        return invite

    async def list_invites(self, household_id: int) -> Sequence[Invite]:
        return await self.invites.list_pending_by_household(household_id)

    async def revoke_invite(self, household_id: int, invite_id: int) -> None:
        invite = await self.invites.get_by_id(invite_id)
        if invite is None or invite.household_id != household_id:
            raise NotFoundError("Invite not found")
        if invite.revoked or invite.accepted_at is not None:
            raise ValidationAppError("Invite is no longer pending")
        await self.invites.revoke(invite)

    async def join_household(self, user: User, token: str) -> HouseholdMember:
        # Users may retype a join code in any case or with stray whitespace —
        # get_by_token does a case-insensitive match, so just trim here.
        invite = await self.invites.get_by_token(token.strip())
        if invite is None:
            raise NotFoundError("Invite not found")
        if invite.revoked or invite.accepted_at is not None:
            raise ValidationAppError("This invite is no longer valid")
        if invite.expires_at < datetime.utcnow():
            raise ValidationAppError("This invite has expired")

        existing_membership = await self.members.get_by_user(user.id)
        if existing_membership is not None:
            raise ConflictError("You already belong to a household — v1 supports only one per user")

        membership = await self._add_member_or_raise(
            invite.household_id, user.id, MemberRole.MEMBER
        )
        await self.invites.mark_accepted(invite)
        return membership

    async def remove_member(self, household_id: int, member_id: int) -> None:
        member = await self.members.get_by_id(member_id)
        if member is None or member.household_id != household_id:
            raise NotFoundError("Member not found")
        if member.role == MemberRole.OWNER:
            raise ConflictError("Cannot remove the household's Owner — transfer ownership first")
        await self.members.delete(member)
        await self.households.release_member_slot(household_id)

    async def leave_household(self, membership: HouseholdMember) -> None:
        if membership.role == MemberRole.OWNER:
            raise ConflictError(
                "Transfer ownership to another Admin before leaving — a household must always have an Owner"
            )
        await self.members.delete(membership)
        await self.households.release_member_slot(membership.household_id)

    async def update_member_role(
        self,
        household_id: int,
        member_id: int,
        new_role: MemberRole,
        acting_membership: HouseholdMember,
    ) -> HouseholdMember:
        member = await self.members.get_by_id(member_id)
        if member is None or member.household_id != household_id:
            raise NotFoundError("Member not found")

        if new_role == MemberRole.OWNER:
            return await self._transfer_ownership(member, acting_membership)

        if member.role == MemberRole.OWNER:
            raise ConflictError(
                "Cannot change the Owner's role directly — transfer ownership instead"
            )

        return await self.members.update_role(member, new_role)

    async def _transfer_ownership(
        self, member: HouseholdMember, acting_membership: HouseholdMember
    ) -> HouseholdMember:
        """Owner is single-holder: only the current Owner can hand the role off, and
        only to an existing Admin — matches the client's promote-to-owner flow, which
        only ever offers that action on Admin rows. The outgoing Owner is demoted to
        Admin in the same operation so the household is never without one.
        """
        if acting_membership.role != MemberRole.OWNER:
            raise PermissionDeniedError("Only the current Owner can transfer ownership")
        if member.id == acting_membership.id:
            raise ValidationAppError("You are already the Owner")
        if member.role != MemberRole.ADMIN:
            raise ValidationAppError("Only an Admin can be promoted to Owner")

        new_owner = await self.members.update_role(member, MemberRole.OWNER)
        await self.members.update_role(acting_membership, MemberRole.ADMIN)
        return new_owner

    async def get_membership_for_user(self, user_id: int) -> Optional[HouseholdMember]:
        return await self.members.get_by_user(user_id)

    async def remove_user_for_account_deletion(self, user: User) -> None:
        """Detach a deleting user from their household — called by AuthService.delete_account.

        Unlike leave_household (the API path, which blocks an Owner outright), this
        always succeeds: an Owner's role is auto-transferred to the longest-tenured
        Admin (or, if no Admin exists, the longest-tenured Member) before their
        membership is removed, since there's no one left to ask to transfer it
        manually. If the Owner is the household's only member, the whole household —
        and, via its cascading relationships, its budget/categories/transactions/
        invites — is deleted instead of leaving an ownerless, memberless shell.
        """
        membership = await self.members.get_by_user(user.id)
        if membership is None:
            return

        if membership.role != MemberRole.OWNER:
            await self.members.delete(membership)
            await self.households.release_member_slot(membership.household_id)
            return

        other_members = [
            m
            for m in await self.members.list_by_household(membership.household_id)
            if m.id != membership.id
        ]
        if not other_members:
            household = await self.get_household_or_404(membership.household_id)
            await self.households.delete(household)
            return

        admins = [m for m in other_members if m.role == MemberRole.ADMIN]
        successor = min(admins or other_members, key=lambda m: m.joined_at)
        await self.members.update_role(successor, MemberRole.OWNER)
        await self.members.delete(membership)
        await self.households.release_member_slot(membership.household_id)
