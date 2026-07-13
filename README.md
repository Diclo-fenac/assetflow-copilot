# AssetFlow Copilot

AssetFlow Copilot bridges live IT inventory with Slack. Employees request hardware and managers approve allocations instantly through a fully autonomous, closed-loop AI assistant.

## Architecture

* **Slack Bolt (Python):** Handles incoming mentions, interactive block kit buttons, and App Home tab events.
* **FastAPI:** Serves the Slack events endpoint and orchestrates background tasks (overdue asset daemon).
* **LangGraph + Gemini 2.5 Flash:** Provides the autonomous LLM agent with state tracking.
* **MCP / Services:** The LLM agent uses Model Context Protocol-style tools to query a live Node.js/MySQL inventory backend securely.

## Setup Instructions

### Prerequisites

* Python 3.13+
* `uv` package manager
* A running instance of the AssetFlow Node API

### 1. Environment Variables

Copy `.env.example` to `.env` and fill in the required keys:

* `SLACK_BOT_TOKEN`: Starts with `xoxb-`. Get from Slack API -> OAuth & Permissions.
* `SLACK_SIGNING_SECRET`: Get from Slack API -> Basic Information.
* `SLACK_APP_TOKEN`: Starts with `xapp-`. Get from Slack API -> App-Level Tokens.
* `GOOGLE_API_KEY`: Get from Google AI Studio.
* `ASSETFLOW_ADMIN_TOKEN`: A valid JWT admin token from the Node.js backend.

### 2. Install Dependencies

```bash
uv pip install -r requirements.txt
```

### 3. Database Initialization

```bash
uv run python seed.py
```
This initializes the local SQLite database used for tracking Slack-specific mappings and pending requests.

### 4. Run the Server

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. Expose Locally (For Slack Webhooks)

```bash
ngrok http 8000
```
Update your Slack API Event Subscriptions and Interactivity request URLs with the resulting ngrok URL.
