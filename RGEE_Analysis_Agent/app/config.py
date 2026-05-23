"""Configuration for RGEE_Analysis_Agent."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_database_url: str = Field(
        default="sqlite:///./rgee_analysis_agent.db",
        alias="RGEE_ANALYSIS_AGENT_DATABASE_URL",
    )
    question_analysis_st_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="QUESTION_ANALYSIS_ST_MODEL",
    )
    api_secret: str = Field(default="", alias="RGEE_ANALYSIS_AGENT_SECRET")
    require_api_secret: bool = Field(default=False, alias="RGEE_ANALYSIS_AGENT_REQUIRE_SECRET")
    listen_host: str = Field(default="127.0.0.1", alias="RGEE_ANALYSIS_AGENT_HOST")
    listen_port: int = Field(default=8010, alias="RGEE_ANALYSIS_AGENT_PORT")

    @field_validator("require_api_secret", mode="before")
    @classmethod
    def _coerce_bool(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()
