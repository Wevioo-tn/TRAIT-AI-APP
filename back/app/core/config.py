"""Application configuration, sourced entirely from environment variables.

No secrets are hardcoded here: every value has a safe local-dev default so the
app boots out of the box with docker-compose, but production deployments are
expected to override every one of these via the environment (see .env.example
at the repo root).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application database (traites, audit trail, decisions, ...)
    database_url: str = "postgresql+psycopg://trait:trait@postgres:5432/trait_ai"

    # Dedicated database used only by the automated test suite. Kept separate
    # from the dev database so tests never touch real/seeded data.
    database_url_test: str = "postgresql+psycopg://trait:trait@postgres:5432/trait_ai_test"

    app_name: str = "TRAIT-AI Backend"
    api_prefix: str = "/api"
    environment: str = "development"

    # Backed by a named Docker volume (see docker-compose.yml) so uploads
    # survive container restarts without polluting the bind-mounted source
    # tree with binary files.
    upload_dir: str = "/app/uploads"
    max_upload_size_bytes: int = 15 * 1024 * 1024  # 15 MB

    # "Seuil_1" from the design mockup — the NLP match score (0-100) above
    # which a tireur/tiré reconciliation counts as automatically confirmed.
    nlp_match_threshold: float = 95.0

    # Below this score, a débiteur already identified with certainty by RIB
    # (see app/services/nlp_matching.py's match_debiteur_by_rib) has a
    # scanned party name that looks nothing like that débiteur's real
    # raison_sociale — a possible wrong-document/homonym mismatch worth a
    # human's attention. Deliberately never used to override or reject the
    # RIB match itself (that's a hard key from the bank instrument); only to
    # flag the écart explicitly instead of silently ignoring it.
    rib_corroboration_min_score: float = 50.0

    # Browsers enforce CORS, curl doesn't — every earlier "live smoke test"
    # in this project used curl and would have missed a missing CORS
    # config entirely. Caught live via an actual browser (Playwright) in
    # Sprint 5. Comma-separated in the env var; production should set this
    # to the real frontend origin(s), not widen it further.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    # HS256 dev default — production MUST override this via env var. Not a
    # secret worth protecting in this repo (there is no production secret
    # here), but flagged so it's never mistaken for one.
    jwt_secret: str = "dev-only-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 480  # one working day

    # Real OCR/extraction (Sprint 8) — a vision-capable LLM behind the same
    # Extractor seam StubExtractor has always implemented (see
    # app/services/extraction.py). Defaults to "stub" — a misconfigured or
    # unset provider must never silently start making real (and possibly
    # billed) external calls.
    ocr_provider: str = "stub"

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-08-01-preview"


@lru_cache
def get_settings() -> Settings:
    return Settings()
