from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.controllers import auth_controller
from app.core.security import get_client_ip
from app.schemas.auth import DeleteAccountRequest, ForgotPinRequest, LoginRequest, LoginResponse
from app.schemas.user import UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    """Create an account. The user chooses their own 6-digit PIN (payload.pin) at signup —
    unlike forgot-PIN, nothing is generated or emailed here."""
    return await auth_controller.signup(db, payload)


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Exchange email + PIN for a bearer access token."""
    ip_address = get_client_ip(request)
    return await auth_controller.login(db, payload, ip_address)


@router.post("/forgot-pin", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def forgot_pin(payload: ForgotPinRequest, db: AsyncSession = Depends(get_db)):
    """Issue and email a new PIN, invalidating the old one.

    Always responds 204 regardless of whether the email is registered, so the
    endpoint can't be used to enumerate accounts.
    """
    await auth_controller.forgot_pin(db, payload)


@router.post("/delete-account", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_account(
    payload: DeleteAccountRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    """Authenticate with email + PIN and permanently delete the account and its data.

    Required by Google Play Console's account/data deletion policy — reachable without
    an existing session, since the whole point is that a user can request deletion by
    proving ownership of the account (email + PIN) rather than needing to be signed in.
    """
    ip_address = get_client_ip(request)
    await auth_controller.delete_account(db, payload, ip_address)
