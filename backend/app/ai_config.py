"""Central configuration for WantToKnow.info AI synthesis.

The DeepInfra key below is intentionally a local-development placeholder.
Replace only DEEPINFRA_API_KEY locally. Do not expose this module through the
static site, commit a real key to source control, or return it in API errors.
"""

from __future__ import annotations

import os

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
RUNTIME_DIR = BACKEND_ROOT / "runtime"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "search_syntheses.md"

# ---------------------------------------------------------------------------
# DeepInfra / model configuration
# ---------------------------------------------------------------------------

DEEPINFRA_MODEL = "NousResearch/Hermes-3-Llama-3.1-70B"
DEEPINFRA_ENDPOINT = "https://api.deepinfra.com/v1/openai/chat/completions"

# DeepInfra credentials are supplied only through the process environment.
#
# Production:
#   systemd loads DEEPINFRA_API_KEY from a root-controlled EnvironmentFile.
#
# Local development:
#   export DEEPINFRA_API_KEY in the shell before starting Uvicorn.
#
# An absent key intentionally leaves AI synthesis unavailable while the rest
# of the WantToKnow.info application continues to operate normally.
DEEPINFRA_API_KEY_PLACEHOLDER = "PASTE_YOUR_LOCAL_DEEPINFRA_KEY_HERE"
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()

AI_INFERENCE_TIMEOUT_SECONDS = 120
AI_CONNECT_TIMEOUT_SECONDS = 15
AI_TEMPERATURE = 0.25
AI_MAX_GENERATED_TOKENS = 1800

# ---------------------------------------------------------------------------
# Retrieval / context configuration
# ---------------------------------------------------------------------------

AI_SOURCE_COUNT = 5
AI_PER_SOURCE_CONTEXT_CHARS = 10_000
AI_TOTAL_CONTEXT_CHARS = 50_000

# ---------------------------------------------------------------------------
# Browser gating and server-side request coordination
# ---------------------------------------------------------------------------

AI_INITIAL_BUTTON_DELAY_SECONDS = 5
AI_COOLDOWN_SECONDS = 15
AI_ACTIVE_REQUEST_LEASE_SECONDS = 180
AI_STATE_RETENTION_SECONDS = 86_400

AI_STATE_DB_PATH = RUNTIME_DIR / "ai-state.sqlite"
AI_QUALITY_RATING_DEFAULT = "plus"

AI_QUALITY_PLUS_LOG_PATH = (
    RUNTIME_DIR / "search-synthesis-quality.jsonl"
)

AI_QUALITY_PLUS_LOG_LOCK_PATH = (
    RUNTIME_DIR / "search-synthesis-quality.jsonl.lock"
)

AI_QUALITY_MINUS_LOG_PATH = (
    RUNTIME_DIR / "search-synthesis-quality-minus.jsonl"
)

AI_QUALITY_MINUS_LOG_LOCK_PATH = (
    RUNTIME_DIR / "search-synthesis-quality-minus.jsonl.lock"
)

# The browser control defaults to + / opted in. This value is exposed through
# the public synthesis config endpoint so the default remains centralized.
AI_QUALITY_LOG_DEFAULT = True
