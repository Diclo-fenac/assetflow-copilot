from datetime import datetime, timezone

from sqlalchemy import String, Integer, Text, DateTime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class TenantMapping(Base):
    __tablename__ = "tenant_mappings"

    slack_workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    assetflow_org_id: Mapped[int] = mapped_column(Integer, nullable=False)
    admin_token: Mapped[str] = mapped_column(Text, nullable=False)
    approvals_channel_id: Mapped[str] = mapped_column(String, nullable=True)


class UserMapping(Base):
    __tablename__ = "user_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slack_user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    slack_workspace_id: Mapped[str] = mapped_column(String, nullable=False)
    assetflow_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)


class AssetRequest(Base):
    __tablename__ = "asset_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slack_user_id: Mapped[str] = mapped_column(String, nullable=False)
    slack_workspace_id: Mapped[str] = mapped_column(String, nullable=False)
    assetflow_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_tag: Mapped[str] = mapped_column(String, nullable=False)
    asset_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="Draft")
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_by_slack_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approval_message_ts: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, onupdate=lambda: datetime.now(timezone.utc), nullable=True
    )


engine = create_async_engine(get_settings().database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
async_session = AsyncSessionLocal  # alias


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
