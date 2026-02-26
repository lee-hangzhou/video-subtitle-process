from pathlib import Path
from typing import List

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class AlibabaSettings(BaseModel):
    access_key_id: str = ""
    access_key_secret: str = ""
    oss_endpoint: str = ""
    oss_bucket_name: str = ""
    oss_input_prefix: str = "video-tasks/input"
    oss_output_prefix: str = "video-tasks/output"


class QuVideoSettings(BaseModel):
    ak: str = ""
    sk: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(_ENV_FILE), ".env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",
    )

    PROJECT_NAME: str = "video-subtitle-process"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"

    ENV: str = Field(default="dev")
    DEBUG: bool = Field(default=False)
    PORT: int = Field(default=8000)

    DATABASE_URL: str = Field(default="sqlite://./video_subtitle_process.db")

    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    REDIS_MAX_CONNECTIONS: int = Field(default=10)

    JWT_SECRET_KEY: str = Field(default="dev-secret-key-change-in-production")
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    CORS_ORIGINS: str = Field(default="")

    LOG_LEVEL: str = Field(default="INFO")
    LOG_FORMAT: str = Field(default="json")

    alibaba: AlibabaSettings = Field(default_factory=AlibabaSettings)
    quvideo: QuVideoSettings = Field(default_factory=QuVideoSettings)

    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/1")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/2")

    FFMPEG_WORKERS: int = Field(default=2)
    TMP_DIR: str = Field(default="/tmp/video-process")

    @property
    def cors_origins_list(self) -> List[str]:
        if not self.CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
