import re

with open("/home/mium/code/assetflow-copilot/app/bot/slack_app.py", "r") as f:
    code = f.read()

old_home_tab = """def build_home_tab(user_assets: list[dict], pending_requests: list[AssetRequest] = None) -> dict:
    \"\"\"Build App Home tab view.\"\"\"
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "AssetFlow Agent"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*My Active Assets* ({len(user_assets)})"},
        },
    ]

    if not user_assets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No assets currently assigned to you._"},
        })
    else:
        for a in user_assets[:5]:
            cat = a.get("Category", {})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"• *{a.get('name', '?')}* (`{a.get('tag', '?')}`)\\n"
                        f"  Category: {cat.get('name', 'N/A')}  |  Condition: {a.get('condition', 'N/A')}  |  Location: {a.get('location', 'N/A')}"
                    ),
                },
            })

    blocks.append({"type": "divider"})

    # Pending requests section
    if pending_requests:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Pending Requests* ({len(pending_requests)})"},
        })
        for r in pending_requests[:5]:
            status_indicator = "Pending" if r.status == "Pending" else r.status
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• `REQ-{r.id:04d}`: {r.asset_name} (`{r.asset_tag}`) — Status: *{status_indicator}*",
                },
            })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No pending requests._"},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Refresh"},
                "action_id": "refresh_home",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Help / What can I do?"},
                "action_id": "show_help_menu",
            },
        ],
    })

    return {"type": "home", "blocks": blocks}"""

new_home_tab = """def build_home_tab(user_assets: list[dict], pending_requests: list[AssetRequest] = None) -> dict:
    \"\"\"Build App Home tab view.\"\"\"
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🚀 AssetFlow Copilot Dashboard"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Your autonomous AI IT Assistant. Use this dashboard to manage your hardware."}]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*:briefcase: My Active Assets ({len(user_assets)})*\\n_Equipment currently checked out to you._"},
        },
    ]

    if not user_assets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "You have a clean slate! No assets assigned yet. Need something? Just message me!"},
        })
    else:
        for a in user_assets[:5]:
            cat = a.get("Category", {})
            condition_emoji = "🟢" if a.get('condition') == "Good" else ("🟡" if a.get('condition') == "Fair" else "🔴")
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{a.get('name', '?')}* (`{a.get('tag', '?')}`)\\n"
                        f"{condition_emoji} *Condition:* {a.get('condition', 'N/A')}  |  🏢 *Location:* {a.get('location', 'N/A')}\\n"
                        f"📦 *Category:* {cat.get('name', 'N/A')}"
                    ),
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Report Issue"},
                    "action_id": "report_issue",
                    "value": a.get('tag', '?'),
                },
            })

    blocks.append({"type": "divider"})

    # Pending requests section
    if pending_requests:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*:hourglass_flowing_sand: Pending Requests ({len(pending_requests)})*\\n_Waiting for manager approval._"},
        })
        for r in pending_requests[:5]:
            status_indicator = "⏳ Pending" if r.status == "Pending" else f"✅ {r.status}"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• `REQ-{r.id:04d}`: *{r.asset_name}* (`{r.asset_tag}`)\\nStatus: {status_indicator}",
                },
            })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "No pending requests."},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🔄 Refresh Dashboard", "emoji": True},
                "action_id": "refresh_home",
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🤖 What can I do?", "emoji": True},
                "action_id": "show_help_menu",
            },
        ],
    })

    return {"type": "home", "blocks": blocks}"""

code = code.replace(old_home_tab, new_home_tab)

with open("/home/mium/code/assetflow-copilot/app/bot/slack_app.py", "w") as f:
    f.write(code)

print("Home Tab upgraded.")
