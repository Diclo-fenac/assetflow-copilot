"""
Seed script — populate local SQLite with demo tenant + user mappings.
Run: python seed.py
"""

import asyncio
from app.db.database import init_db, AsyncSessionLocal, TenantMapping, UserMapping


async def seed():
    await init_db()

    async with AsyncSessionLocal() as session:
        # Tenant mapping
        tenant = TenantMapping(
            slack_workspace_id="T0BGEMDKKT9",
            assetflow_org_id=1,
            admin_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MSwibmFtZSI6IkFkbWluIiwiZW1haWwiOiJhZG1pbkBhc3NldGZsb3cubG9jYWwiLCJpYXQiOjE3ODM5MjU5NzIsImV4cCI6NDkzOTY4NTk3Mn0.D0pPQo3k2v5ssp03fIJbIri7ujWy6AlS0UA1ICgqi2I",
            approvals_channel_id="C0BGY0TSC5P",
        )
        session.add(tenant)

        # Demo users — map Slack user IDs to AssetFlow user IDs
        users = [
            UserMapping(
                slack_user_id="U0BGW2TB23C",  # Employee (and Manager for demo)
                slack_workspace_id="T0BGEMDKKT9",
                assetflow_user_id=1,
                email="user@example.com",
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
