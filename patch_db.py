import re

with open("/home/mium/code/assetflow-copilot/app/db/database.py", "r") as f:
    code = f.read()

old_mappings = """class UserMapping(Base):
    __tablename__ = "slack_user_mapping"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    slack_user_id: Mapped[str] = mapped_column(index=True, unique=True)
    assetflow_user_id: Mapped[int] = mapped_column(index=True)
    email: Mapped[str] = mapped_column()


class TenantMapping(Base):
    __tablename__ = "slack_tenant_mapping"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    slack_workspace_id: Mapped[str] = mapped_column(index=True, unique=True)
    assetflow_org_id: Mapped[int] = mapped_column(index=True)
    approvals_channel_id: Mapped[str] = mapped_column(nullable=True)"""

code = code.replace(old_mappings, "")

with open("/home/mium/code/assetflow-copilot/app/db/database.py", "w") as f:
    f.write(code)

print("Removed UserMapping and TenantMapping from database.py.")
