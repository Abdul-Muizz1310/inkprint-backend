"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Inkprint backend settings — validated at boot, crashes on missing required keys."""

    model_config = {"env_file": ".env", "extra": "ignore"}

    # ─── Core ────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "debug"
    port: int = 8000

    # ─── Database ────────────────────────────────────
    database_url: str = ""

    # ─── Signing keys ────────────────────────────────
    inkprint_signing_key_private: str = ""
    inkprint_signing_key_public: str = ""
    inkprint_key_id: str = "inkprint-ed25519-2026-04"

    # ─── Embeddings ──────────────────────────────────
    voyage_api_key: str = ""
    voyage_model: str = "voyage-3-lite"

    # ─── LLM (optional) ─────────────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model_primary: str = ""

    # ─── Cloudflare R2 ──────────────────────────────
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "muizz-lab"
    r2_endpoint: str = ""
    r2_public_base: str = ""

    # ─── Leak corpora ───────────────────────────────
    common_crawl_cdx: str = "https://index.commoncrawl.org/CC-MAIN-2024-50-index"
    hf_datasets_api: str = "https://datasets-server.huggingface.co"
    bigcode_stack_api: str = "https://huggingface.co/api/datasets/bigcode/the-stack-v2"

    # ─── Thresholds ─────────────────────────────────
    leak_confidence_threshold: float = 0.7
    derivative_hamming_threshold: int = 12
    derivative_cosine_threshold: float = 0.85
    max_text_bytes: int = 500_000

    # ─── Platform ───────────────────────────────────
    bastion_public_key_url: str = "https://bastion.vercel.app/api/public-key"
    demo_mode: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
