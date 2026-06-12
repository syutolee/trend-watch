from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")

    # provider: anthropic | ollama | groq
    provider: str = "ollama"
    api_key: SecretStr = SecretStr("ollama")
    model: str = "gemma4:e4b"
    max_tokens: int = 8192
    temperature: float = 0.3
    # For ollama: http://localhost:11434/v1  For groq: https://api.groq.com/openai/v1
    base_url: str = "http://localhost:11434/v1"


class CrawlerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRAWLER_")

    request_timeout: int = 30
    max_retries: int = 3
    min_delay: float = 1.5
    max_delay: float = 3.5


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    debug: bool = False
    log_level: str = "INFO"

    llm: LLMSettings = Field(default_factory=LLMSettings)
    crawler: CrawlerSettings = Field(default_factory=CrawlerSettings)

    dictionary_dir: Path = Path("data/dictionaries")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
