"""
Seed script — populate local SQLite with demo tenant + user mappings.
Run: python seed.py
"""

import asyncio
from app.db.database import init_db, AsyncSessionLocal, TenantMapping, UserMapping

from app.core.config import settings

async def seed():
    await init_db()

    async with AsyncSessionLocal() as session:
        # Tenant mapping
        tenant = TenantMapping(
            slack_workspace_id="T0BGEMDKKT9",
            assetflow_org_id=1,
            admin_token=settings.assetflow_admin_token,
            approvals_channel_id="C0BGY0TSC5P",
        )
        session.add(tenant)

        # Demo users — map Slack user IDs to AssetFlow user IDs
        users = [
            UserMapping(
                slack_user_id="U0BGW2TB23C",  # Employee (and Manager for demo)
                slack_workspace_id="T0BGEMDKKT9",
                assetflow_user_id=1,
                email="mayank@example.com",
            ),
        ]
        session.add_all(users)

        try:
            await session.commit()
            print("Seed data inserted.")
        except Exception as e:
            await session.rollback()
            print(f"Seed failed (may already exist): {e}")


if __name__ == "__main__":
    asyncio.run(seed())
