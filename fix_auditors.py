import re
path = "/home/mium/code/assetflow-copilot/app/bot/slack_app.py"
with open(path, "r") as f:
    content = f.read()

content = content.replace(
    "await api.assign_auditors(cycle_id, [mapping.assetflow_user_id])",
    "members = await api.get_members()\n        admin_ids = [m['User']['id'] for m in members if m.get('role') == 'Admin']\n        await api.assign_auditors(cycle_id, [mapping.assetflow_user_id] + admin_ids)"
)

with open(path, "w") as f:
    f.write(content)
