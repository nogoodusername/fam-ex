import secrets
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import send_pin_email
from app.core.exceptions import AuthenticationError, ConflictError, RateLimitError
from app.core.security import create_access_token, generate_pin, hash_pin, verify_pin
from app.models.user import User
from app.repositories.login_attempt_repository import LoginAttemptRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.household_service import HouseholdService


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepository(db)
        self.login_attempts = LoginAttemptRepository(db)
        self.households = HouseholdService(db)

    async def signup(self, payload: UserCreate) -> User:
        existing = await self.users.get_by_email(payload.email)
        if existing is not None:
            raise ConflictError("An account with this email already exists")

        # PIN is user-chosen at signup (payload.pin), not server-generated — unlike forgot_pin
        # below, which still generates+emails one since that flow's whole point is recovering an
        # account the user is locked out of. No email is sent here: there's nothing to deliver
        # since the user already knows the PIN they just typed.
        user = await self.users.create(
            email=payload.email,
            full_name=payload.full_name,
            nickname=payload.nickname,
            pin_hash=hash_pin(payload.pin),
        )
        return user

    async def _authenticate(self, email: str, pin: str, ip_address: str) -> User:
        """Shared by login and delete_account — both need to verify email+PIN under
        the same per-IP/per-account throttles before doing anything else. A deleted
        (tombstoned) account can never reach here: its email was overwritten at
        deletion time, so a lookup by the original email simply finds nothing.
        """
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=settings.IP_LOCKOUT_WINDOW_MINUTES)
        recent_ip_failures = await self.login_attempts.count_recent_failures(
            ip_address, since=window_start
        )
        if recent_ip_failures >= settings.MAX_LOGIN_FAILURES_PER_IP:
            raise RateLimitError("Too many failed login attempts. Try again later.")

        user = await self.users.get_by_email(email)
        if user is None:
            await self.login_attempts.record_failure(ip_address)
            raise AuthenticationError("Invalid email or PIN")

        if user.locked_until is not None and user.locked_until > now:
            minutes_left = max(1, int((user.locked_until - now).total_seconds() // 60))
            raise AuthenticationError(
                f"Too many failed attempts. Try again in {minutes_left} minute(s)."
            )

        if not verify_pin(pin, user.pin_hash):
            locked_until = None
            if user.failed_login_attempts + 1 >= settings.MAX_LOGIN_ATTEMPTS:
                locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            await self.users.record_failed_login(user, locked_until=locked_until)
            await self.login_attempts.record_failure(ip_address)
            raise AuthenticationError("Invalid email or PIN")

        if user.failed_login_attempts or user.locked_until is not None:
            await self.users.reset_login_attempts(user)

        return user

    async def login(self, email: str, pin: str, ip_address: str) -> tuple[User, str]:
        user = await self._authenticate(email, pin, ip_address)
        token = create_access_token(subject=user.id)
        return user, token

    async def delete_account(self, email: str, pin: str, ip_address: str) -> None:
        """Authenticate with email + PIN, then permanently delete the account: detach
        it from its household (transferring ownership or deleting the household
        outright if it's the sole member — see HouseholdService.
        remove_user_for_account_deletion), and anonymize the user row rather than
        hard-deleting it, since transactions.paid_by_id/created_by_id cascade-delete
        on user removal and would otherwise wipe shared household history still
        relied on by other members.
        """
        user = await self._authenticate(email, pin, ip_address)
        await self.households.remove_user_for_account_deletion(user)
        await self.users.update(
            user,
            email=f"deleted-user-{user.id}@deleted.budgeyet.invalid",
            full_name="Deleted User",
            nickname="Deleted",
            pin_hash=hash_pin(secrets.token_hex(32)),
            is_deleted=True,
            deleted_at=datetime.utcnow(),
        )

    async def forgot_pin(self, email: str) -> None:
        """Issue a fresh, server-generated PIN and email it — unlike signup, where the user
        chooses their own PIN, this flow has no other way to hand the user a working PIN.

        Silently no-ops for unknown emails so the endpoint can't be used to
        enumerate registered accounts.
        """
        user = await self.users.get_by_email(email)
        if user is None:
            return

        pin = generate_pin()
        await self.users.update(user, pin_hash=hash_pin(pin))
        await self.users.reset_login_attempts(user)
        await send_pin_email(user.email, pin)
