import re

with open("/home/mium/code/assetflow-copilot/app/services/assetflow_api.py", "r") as f:
    api_code = f.read()

if "link_slack_account" not in api_code:
    new_func = """
async def link_slack_account(email: str, slack_user_id: str) -> dict[str, Any] | None:
    \"\"\"POST /api/auth/link-slack\"\"\"
    try:
        resp = await _get_client().post("/api/auth/link-slack", json={"email": email, "slack_user_id": slack_user_id})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("link_slack_account failed")
        return None
"""
    api_code += new_func
    with open("/home/mium/code/assetflow-copilot/app/services/assetflow_api.py", "w") as f:
        f.write(api_code)

with open("/home/mium/code/assetflow-copilot/app/bot/slack_app.py", "r") as f:
    slack_code = f.read()

if "@app.command(\"/link-account\")" not in slack_code:
    cmd_code = """
@app.command("/link-account")
async def handle_link_account(ack, respond, command):
    await ack()
    text = command.get("text", "").strip()
    slack_user_id = command.get("user_id")
    
    if not text or "@" not in text:
        await respond("Usage: /link-account <your-email@example.com>")
        return
        
    res = await api.link_slack_account(text, slack_user_id)
    if res:
        await respond(f"✅ Successfully linked your Slack account to {text} in AssetFlow!")
    else:
        await respond("❌ Failed to link account. Please check the email and try again.")
"""
    slack_code += cmd_code
    with open("/home/mium/code/assetflow-copilot/app/bot/slack_app.py", "w") as f:
        f.write(slack_code)

print("Copilot updated.")
