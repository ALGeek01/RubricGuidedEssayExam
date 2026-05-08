from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Together "Small & Fast" tier — used for every chat/completions call unless overridden (see together_use_env_model).
# https://docs.together.ai/docs/recommended-models
TOGETHER_CHAT_MODEL_DEFAULT = "openai/gpt-oss-20b"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    together_api_key: str = ""
    # Read from TOGETHER_MODEL in .env; only applied when together_use_env_model is True.
    together_model_from_env: str = Field(default=TOGETHER_CHAT_MODEL_DEFAULT, alias="TOGETHER_MODEL")
    # When False (default), all requests use TOGETHER_CHAT_MODEL_DEFAULT so old .env examples cannot force slow models.
    # Set TOGETHER_USE_ENV_MODEL=1 to honor TOGETHER_MODEL for custom / higher-quality models.
    together_use_env_model: bool = Field(default=False, alias="TOGETHER_USE_ENV_MODEL")
    # Official inference host (see https://docs.together.ai/docs/api-keys-authentication)
    together_base_url: str = "https://api.together.xyz/v1"
    mock_llm: bool = False

    def together_model_for_requests(self) -> str:
        """Model id for Together chat/completions — single source of truth for the app."""
        if self.together_use_env_model:
            m = (self.together_model_from_env or "").strip()
            return m if m else TOGETHER_CHAT_MODEL_DEFAULT
        return TOGETHER_CHAT_MODEL_DEFAULT

    @field_validator("together_api_key", mode="before")
    @classmethod
    def _normalize_api_key(cls, v):
        if v is None:
            return ""
        s = str(v).strip().strip('"').strip("'")
        return s

    @field_validator("mock_llm", mode="before")
    @classmethod
    def _coerce_mock(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)
    database_url: str = "sqlite:///./exam_system.db"

    # Instructor login: session cookie signing (use a long random value in production).
    instructor_session_secret: str = Field(
        default="rgee-instructor-session-dev-key-min-32-chars!!",
        alias="INSTRUCTOR_SESSION_SECRET",
    )
    # Optional path to JSON with username_sha256 / password_pbkdf2_hex (see app/instructor_auth.py).
    instructor_credentials_path: str = Field(default="", alias="INSTRUCTOR_CREDENTIALS_PATH")
    # Override expected derivatives when no credentials file is used.
    instructor_username_sha256: str = Field(default="", alias="INSTRUCTOR_USERNAME_SHA256")
    instructor_password_pbkdf2_hex: str = Field(default="", alias="INSTRUCTOR_PASSWORD_PBKDF2_HEX")

    # Hugging Face sentence-transformers model id (PyTorch) for instructor question analysis.
    question_analysis_st_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="QUESTION_ANALYSIS_ST_MODEL",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
