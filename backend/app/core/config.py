from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，环境变量优先（支持项目根目录 .env）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://compass:compass@localhost:5432/compass"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "compass"
    minio_secret_key: str = "compass-secret"
    minio_bucket: str = "compass-attachments"
    minio_secure: bool = False

    # LLM（M2 启用）
    deepseek_api_key: str = ""
    llm_extract_model: str = "deepseek/deepseek-v4-flash"
    # Embedding（M2 启用，走 SiliconFlow 等 API）
    siliconflow_api_key: str = ""
    embedding_model: str = "openai/BAAI/bge-m3"
    embedding_dim: int = 1024

    # 认证（§10.3）
    jwt_secret: str = "compass-dev-secret-change-in-prod"
    jwt_expire_hours: int = 72

    # SMTP（邮件通知，M4；未配置则跳过该渠道）
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""

    # 采集礼貌性约束（§10.4 合规）
    crawler_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    crawler_timeout_seconds: float = 20.0
    crawler_min_interval_seconds: float = 3.0
    # 本机代理做 HTTPS MITM 时置 false（仅开发环境；生产必须保持 true）
    crawler_verify_ssl: bool = True

    # Playwright 浏览器渲染（JS 动态站兜底，tech-design §4.1）
    playwright_headless: bool = True
    browser_render_timeout: float = 30.0
    browser_min_interval_seconds: float = 5.0  # 浏览器渲染更重，间隔更长


settings = Settings()
