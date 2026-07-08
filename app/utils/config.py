"""Configuration — environment variable loading.

Week 6: 研报平台技术预研配置。
"""

import os
from dotenv import load_dotenv

load_dotenv()


def get_env(key: str, default: str | None = None, required: bool = False) -> str:
    """Get environment variable with optional validation."""
    value = os.getenv(key, default)
    if required and value is None:
        raise ValueError(
            f"Environment variable '{key}' is not set. "
            f"Please set it in your .env file or system environment."
        )
    return value


# --- LLM ---
OPENAI_API_KEY: str = get_env("OPENAI_API_KEY", required=True)
OPENAI_BASE_URL: str = get_env("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
OPENAI_MODEL: str = get_env("OPENAI_MODEL", "glm-4.6v")

# --- Tavily Search ---
TAVILY_API_KEY: str = get_env("TAVILY_API_KEY", required=True)

# --- Agent ---
AGENT_MAX_STEPS: int = int(get_env("AGENT_MAX_STEPS", "10"))
