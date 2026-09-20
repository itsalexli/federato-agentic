"""Environment-backed settings. Everything optional except the Federato creds."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

HANDLER_URL = (
    "https://product.federato.ai/integrations-api/handlers"
    "/federato-hack-north?outputOnly=true"
)
# The auth tenant is deliberately different from the product domain. Minting
# against product.federato.ai yields a token the API rejects with 401.
AUTH_URL = "https://auth.product.federato.ai/oauth/token"
AUDIENCE = "https://product.federato.ai/core-api"

CLIENT_ID = os.getenv("FEDERATO_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("FEDERATO_CLIENT_SECRET", "")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
LLM_ENABLED = bool(ANTHROPIC_API_KEY)

ENRICHMENT_ENABLED = os.getenv("ENRICHMENT_ENABLED", "1") not in ("0", "false", "")

TOKEN_CACHE = ROOT / ".token_cache.json"
CACHE_DIR = ROOT / ".cache"
