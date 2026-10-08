"""应用配置：全部来自环境变量 / .env。"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---------- 基础 ----------
    app_env: str = "development"
    app_name: str = "XianyuHub"
    bind_host: str = "127.0.0.1"
    app_port: int = 8000
    app_secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 12
    # 32 字节 base64，用于加密 Cookie / 卡密；为空时开发环境使用派生密钥
    credential_master_key: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # ---------- 存储 ----------
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'xianyuhub.db'}"
    redis_url: str = ""  # 为空时使用进程内实现（单机模式）

    # ---------- 大模型 ----------
    llm_default_provider: str = "openai_compatible"  # anthropic / openai_compatible
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model_vision: str = ""
    llm_model_chat: str = ""
    llm_model_fast: str = ""
    llm_timeout_seconds: float = 60.0
    llm_max_images: int = 4

    # ---------- 风控 ----------
    guard_search_per_min: float = 6
    guard_detail_per_min: float = 10
    guard_message_per_min: float = 20
    guard_publish_per_5min: float = 1
    guard_cooldown_base_seconds: int = 1800
    guard_cooldown_max_seconds: int = 6 * 3600
    guard_jitter_ms_min: int = 500
    guard_jitter_ms_max: int = 3000

    # ---------- 浏览器通道 ----------
    browser_enabled: bool = False
    browser_headless: bool = True

    # ---------- Worker ----------
    run_workers_in_api: bool = True  # 单机模式：API 进程内同时运行调度器 / IM 网关

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
