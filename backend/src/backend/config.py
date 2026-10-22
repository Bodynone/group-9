"""Backend-only configuration. Never send credentials to clients or trace logs."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Settings:
    api_key: str = ""
    base_url: str = "https://api-inference.modelscope.cn/v1"
    model: str = "Qwen/Qwen3.8-Flash-Next"
    database_path: str | Path = ROOT / "backend/data/grading.sqlite3"
    max_model_calls: int = 24
    task_timeout: float = 300
    request_timeout: float = 90
    input_price_cny_per_million: str | None = None
    output_price_cny_per_million: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", cls.base_url),
            model=os.getenv("OPENAI_MODEL", cls.model),
            database_path=os.getenv("DATABASE_PATH", str(ROOT / "backend/data/grading.sqlite3")),
            input_price_cny_per_million=os.getenv("MODEL_INPUT_PRICE_CNY_PER_MILLION"),
            output_price_cny_per_million=os.getenv("MODEL_OUTPUT_PRICE_CNY_PER_MILLION"),
        )
