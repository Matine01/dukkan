"""
Dukkan Cloud - Configuration
Environment-based configuration with secure credential management.
"""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    All sensitive credentials are configured here.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # =========================================================================
    # APPLICATION SETTINGS
    # =========================================================================
    APP_NAME: str = "Dukkan Cloud"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # =========================================================================
    # DATABASE SETTINGS
    # =========================================================================
    DATABASE_URL: str = "postgresql://matine:root1234@192.168.100.15/dukkan_cloud"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

    # =========================================================================
    # PROXMOX VE SETTINGS
    # =========================================================================
    PROXMOX_URL: str = "https://192.168.100.10:8006"
    PROXMOX_USER: str = "root@pam"
    PROXMOX_PASSWORD: str = "Root1234."
    PROXMOX_VERIFY_SSL: bool = False  # Set to True in production with valid certs
    PROXMOX_NODE: str = "cloud"
    PROXMOX_STORAGE: str = "local-lvm"
    PROXMOX_LXC_TEMPLATE: str = "ubuntu-22.04-standard"
    PROXMOX_QEMU_TEMPLATE: int = 9000  # Template VM ID for cloning

    # =========================================================================
    # APACHE GUACAMOLE SETTINGS
    # =========================================================================
    GUACAMOLE_URL: str = "https://cloud.dukkan.ma/guacamole"
    GUACAMOLE_USER: str = "matine"
    GUACAMOLE_PASSWORD: str = "Matine..@@+2022"
    GUACAMOLE_DATASOURCE: str = "mysql"
    GUACAMOLE_GROUP: str = "DUKKAN_CLOUD"

    # =========================================================================
    # SECURITY SETTINGS
    # =========================================================================
    SECRET_KEY: str = "super-secret-dukkan-cloud-key-2024-do-not-share"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Cookie settings for HttpOnly JWT
    COOKIE_SECURE: bool = True  # Must be True in production (HTTPS)
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: Optional[str] = None

    # Password hashing
    BCRYPT_ROUNDS: int = 12

    # =========================================================================
    # CORS SETTINGS
    # =========================================================================
    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://cloud.dukkan.ma",
        "https://app.dukkan.ma",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list = ["*"]
    CORS_ALLOW_HEADERS: list = ["*"]

    # =========================================================================
    # RATE LIMITING
    # =========================================================================
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    # =========================================================================
    # BILLING & PRICING
    # =========================================================================
    PRICE_CPU_CORE_HOUR: float = 0.01  # $0.01 per core per hour
    PRICE_RAM_GB_HOUR: float = 0.005  # $0.005 per GB RAM per hour
    PRICE_STORAGE_GB_HOUR: float = 0.0001  # $0.0001 per GB storage per hour
    BILLING_CURRENCY: str = "USD"
    TAX_RATE: float = 0.0  # 0% default tax

    # =========================================================================
    # WEBSOCKET SETTINGS
    # =========================================================================
    WS_HEARTBEAT_INTERVAL: int = 30  # seconds
    WS_MAX_MESSAGE_SIZE: int = 1024 * 1024  # 1MB

    # =========================================================================
    # LOGGING & AUDIT
    # =========================================================================
    LOG_LEVEL: str = "INFO"
    AUDIT_LOG_ENABLED: bool = True
    AUDIT_LOG_RETENTION_DAYS: int = 90

    # =========================================================================
    # BACKGROUND TASKS
    # =========================================================================
    USAGE_TRACKING_INTERVAL_HOURS: int = 1
    VM_STATUS_CHECK_INTERVAL_MINUTES: int = 5
    INVOICE_GENERATION_DAY: int = 1  # Day of month to generate invoices

    # =========================================================================
    # REDIS (Optional for caching/sessions)
    # =========================================================================
    REDIS_URL: Optional[str] = None  # redis://localhost:6379/0
    CACHE_TTL_SECONDS: int = 300

    @property
    def proxmox_base_url(self) -> str:
        """Get Proxmox API base URL."""
        return f"{self.PROXMOX_URL}/api2/json"

    @property
    def guacamole_base_url(self) -> str:
        """Get Guacamole API base URL."""
        return f"{self.GUACAMOLE_URL}/api"

    @property
    def pricing(self) -> dict:
        """Get pricing configuration as dict."""
        return {
            "cpu_core_hour": self.PRICE_CPU_CORE_HOUR,
            "ram_gb_hour": self.PRICE_RAM_GB_HOUR,
            "storage_gb_hour": self.PRICE_STORAGE_GB_HOUR,
            "currency": self.BILLING_CURRENCY,
            "tax_rate": self.TAX_RATE,
        }


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses LRU cache to avoid reloading settings on every request.
    """
    return Settings()


# Convenience access to settings
settings = get_settings()
