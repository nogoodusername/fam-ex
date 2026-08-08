from pydantic import BaseModel, EmailStr
from app.schemas.user import UserResponse
from app.schemas.user import Token

class LoginRequest(BaseModel):
    email: EmailStr
    pin: str

class LoginResponse(Token):
    user: UserResponse

class ForgotPinRequest(BaseModel):
    email: EmailStr

class DeleteAccountRequest(BaseModel):
    email: EmailStr
    pin: str
