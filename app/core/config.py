from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    slack_bot_token: str = Field(..., alias="SLACK_BOT_TOKEN")
    slack_signing_secret: str = Field(..., alias="SLACK_SIGNING_SECRET")
    slack_app_token: str = Field(..., alias="SLACK_APP_TOKEN")

    assetflow_api_url: str = Field(
        default="http://localhost:3000", alias="ASSETFLOW_API_URL"
    )
    assetflow_admin_token: str = Field(..., alias="ASSETFLOW_ADMIN_TOKEN")
    assetflow_org_id: str = Field(default="1", alias="ASSETFLOW_ORG_ID")

    google_api_key: str = Field(..., alias="GOOGLE_API_KEY")

    slack_approvals_channel: str = Field(
        default="", alias="SLACK_APPROVALS_CHANNEL"
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./agent_local.db", alias="DATABASE_URL"
    )

    class Config:
        env_file = ".env"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
