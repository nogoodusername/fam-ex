from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, Integer, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from app.core.database import Base

class DisplayMode(str, enum.Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_mode: Mapped[DisplayMode] = mapped_column(String(20), default=DisplayMode.SYSTEM, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Account deletion (Google Play "Delete account" requirement) anonymizes the row rather than
    # hard-deleting it — see AuthService.delete_account — since transactions.paid_by_id/
    # created_by_id cascade-delete on user removal, which would wipe shared household history for
    # other members still relying on it. is_deleted permanently locks the (tombstoned) row out of
    # login; deleted_at records when.
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Relationships
    household_memberships = relationship("HouseholdMember", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship(
        "Transaction", back_populates="paid_by_user", foreign_keys="Transaction.paid_by_id"
    )
