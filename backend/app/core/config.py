"""应用配置：全部来自环境变量 / .env。"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
DEV_SECRET = "dev-secret-change-me-please-use-a-long-random-string"
DEV_ENVS = {"development", "dev", "local", "test", "testing"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---------- 基础 ----------
    app_env: str = "development"
    app_name: str = "XianyuHub"
    bind_host: str = "127.0.0.1"
    app_port: int = 8000
    app_secret_key: str = DEV_SECRET
    access_token_expire_minutes: int = 60 * 12
    # 32 字节 base64，用于加密 Cookie / 卡密；为空时开发环境使用派生密钥
    credential_master_key: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # ---------- 存储 ----------
    data_dir: Path = BASE_DIR / "data"  # 上传图片等本地文件
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'xianyuhub.db'}"
    redis_url: str = ""  # 为空时使用进程内实现（单机模式）

    # ---------- 大模型 ----------
    llm_default_provider: str = "anthropic"  # anthropic / openai_compatible
    llm_api_key: str = ""
    llm_base_url: str = ""  # anthropic 留空即官方地址；openai_compatible 必填
    llm_model_vision: str = "claude-opus-5-5"  # 多模态判定、商品文案
    llm_model_chat: str = "claude-opus-5-5"  # 客服回复
    llm_model_fast: str = "claude-opus-5-5"  # 意图分类、粗筛（可按成本改成更便宜的模型）
    llm_anthropic_fallbacks: bool = True  # 拒答时服务端自动回退（仅官方 Claude API）
    llm_timeout_seconds: float = 90.0
    llm_max_images: int = 4
    llm_daily_token_budget: int = 0  # 0 表示不限制；超出后降级为仅规则

    # ---------- 风控 ----------
    guard_rate_multiplier: float = 1.0  # 全局限流倍率：<1 更保守，>1 更激进
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
    # all：单进程（默认）；api / worker：分离部署（需要 REDIS_URL），通过 Redis 跨进程同步
    process_role: str = "all"

    @property
    def is_production(self) -> bool:
        # 只有明确写成开发 / 测试的才算非生产：写错（prod、Production、staging…）一律按生产处理，强制安全密钥
        return self.app_env.strip().lower() not in DEV_ENVS

    @property
    def is_development(self) -> bool:
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()
