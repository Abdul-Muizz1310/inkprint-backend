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

    # ─── Frontend ───────────────────────────────────
    # Base URL the QR code and verify links point at. Defaults to the deployed
    # Vercel frontend; override via env for other environments.
    frontend_base_url: str = "https://inkprint-frontend.vercel.app"

    # ─── Rate limiting ──────────────────────────────
    # Fixed-window throttle on the write/scan endpoints, keyed on
    # ``bastion:{sub}``, ``inkprint-frontend:{address}`` or the bare address
    # (spec 09 §5). On by default so no caller can be driven to burn unbounded
    # paid Voyage-embedding / corpus-scan calls.
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60

    # ─── Platform token (contract v2, spec 09) ──────
    # bastion's Ed25519 key, base64 SPKI DER; wins over the URL when set.
    bastion_signing_key_public: str = ""
    # Fetched (JSON field ``publicKey``) when the key above is empty.
    bastion_public_key_url: str = "https://bastion-six.vercel.app/api/public-key"
    # inkprint-frontend's Ed25519 key, base64 SPKI DER (DR-0030 proxy).
    inkprint_frontend_signing_key_public: str = ""
    # Tolerates a *missing* token only (logged); a present token is always
    # fully verified. A transition switch, off unless the deployment says so.
    demo_mode: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        """The test settings: the only ones under which a keyless deployment fails open."""
        return self.app_env == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
