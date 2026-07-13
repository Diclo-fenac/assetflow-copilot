import re

with open("/home/mium/code/assetflow-copilot/app/bot/slack_app.py", "r") as f:
    code = f.read()

# Replace get_user_mapping
old_get_user = """async def get_user_mapping(slack_user_id: str) -> UserMapping | None:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserMapping).where(UserMapping.slack_user_id == slack_user_id)
        )
        return result.scalar_one_or_none()"""

new_get_user = """class MockUserMapping:
    def __init__(self, af_id, email):
        self.assetflow_user_id = af_id
        self.email = email

async def get_user_mapping(slack_user_id: str) -> MockUserMapping | None:
    members = await api.get_members()
    if not members:
        return None
    for m in members:
        if m.get("User") and m["User"].get("slack_user_id") == slack_user_id:
            return MockUserMapping(m["User"]["id"], m["User"]["email"])
    return None"""

code = code.replace(old_get_user, new_get_user)

# Replace get_tenant
old_get_tenant = """async def get_tenant(slack_workspace_id: str) -> TenantMapping | None:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TenantMapping).where(TenantMapping.slack_workspace_id == slack_workspace_id)
        )
        return result.scalar_one_or_none()"""

new_get_tenant = """async def get_tenant(slack_workspace_id: str):
    return None"""

code = code.replace(old_get_tenant, new_get_tenant)

# Replace audit loop
old_audit_loop = """    ping_count = 0
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        for item in audit_items:
            holder_id = item["Asset"]["current_holder_id"]
            tag = item["Asset"]["tag"]
            name = item["Asset"]["name"]
            item_id = item["id"]
            
            res = await session.execute(select(UserMapping).where(UserMapping.assetflow_user_id == holder_id))
            m = res.scalar_one_or_none()
            if m:
                blocks = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"*IT Audit Check*\\n\\nHi! We are conducting an automated audit for {dept['name']}.\\n\\nDo you currently have this asset in your possession?\\n\\n*{name}* (`{tag}`)"}},
                    {"type": "actions", "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "Yes, I have it"}, "action_id": "audit_yes", "value": str(item_id), "style": "primary"},
                        {"type": "button", "text": {"type": "plain_text", "text": "No, I don't"}, "action_id": "audit_no", "value": str(item_id), "style": "danger"},
                    ]}
                ]
                await client.chat_postMessage(channel=m.slack_user_id, blocks=blocks, text=f"Audit Check: Do you have {name} ({tag})?")
                ping_count += 1"""

new_audit_loop = """    ping_count = 0
    members = await api.get_members()
    member_map = {m["User"]["id"]: m["User"].get("slack_user_id") for m in members if m.get("User")}
    
    for item in audit_items:
        holder_id = item["Asset"]["current_holder_id"]
        tag = item["Asset"]["tag"]
        name = item["Asset"]["name"]
        item_id = item["id"]
        
        slack_id = member_map.get(holder_id)
        if slack_id:
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*IT Audit Check*\\n\\nHi! We are conducting an automated audit for {dept['name']}.\\n\\nDo you currently have this asset in your possession?\\n\\n*{name}* (`{tag}`)"}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Yes, I have it"}, "action_id": "audit_yes", "value": str(item_id), "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "No, I don't"}, "action_id": "audit_no", "value": str(item_id), "style": "danger"},
                ]}
            ]
            await client.chat_postMessage(channel=slack_id, blocks=blocks, text=f"Audit Check: Do you have {name} ({tag})?")
            ping_count += 1"""

code = code.replace(old_audit_loop, new_audit_loop)

# Remove imports from top
code = code.replace(", UserMapping, TenantMapping", "")

with open("/home/mium/code/assetflow-copilot/app/bot/slack_app.py", "w") as f:
    f.write(code)

print("Patched slack_app.py successfully.")
