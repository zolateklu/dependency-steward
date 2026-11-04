from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    operator_token: str = Field(default="", repr=False)
    worker_token: str = Field(default="", repr=False)
    github_token: str = Field(default="", repr=False)
    github_repo: str = ""
    github_workflow: str = "steward-execute.yml"
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    slack_webhook: str = Field(default="", repr=False)
    database_url: str = "sqlite:///./steward.db"
    firestore_project: str = ""
    firestore_collection: str = "dependency-steward"
    frontend_dist: Path = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    node_version: str = "24.6.0"
    npm_version: str = "11.8.0"
    source_paths: list[str] = ["src/schema.ts"]
    daily_scan_hour_eat: int = Field(default=9, ge=0, le=23)
    app_role: Literal["combined", "web", "worker"] = "combined"
    session_ttl_seconds: int = Field(default=14400, ge=300, le=86400)
    session_cookie_secure: bool = True

    def require_ready(self):
        if len(self.operator_token) < 24 or len(self.worker_token) < 24:
            raise ValueError("Set distinct OPERATOR_TOKEN and WORKER_TOKEN values of at least 24 characters")
        if self.operator_token == self.worker_token:
            raise ValueError("Operator and worker tokens must be different")


COMMANDS = ["test:ci", "typecheck", "build"]
