"""Configuration for RGEE_Analysis_Agent."""

from functools import lru_cache

from pydantic import Field
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
    listen_host: str = Field(default="127.0.0.1", alias="RGEE_ANALYSIS_AGENT_HOST")
    listen_port: int = Field(default=8010, alias="RGEE_ANALYSIS_AGENT_PORT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
