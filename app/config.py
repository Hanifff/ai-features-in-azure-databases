"""Environment and shared constants for the demo app and the loaders."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_FILE = ROOT / "data" / "tickets.csv"

SUBSCRIPTION_ID = os.getenv("SUBSCRIPTION_ID", "")
RESOURCE_GROUP = os.getenv("RESOURCE_GROUP", "")

FOUNDRY_MODELS_ENDPOINT = os.environ["FOUNDRY_MODELS_ENDPOINT"]
FOUNDRY_PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
FOUNDRY_ACCOUNT = FOUNDRY_MODELS_ENDPOINT.split("//", 1)[-1].split(".", 1)[0]
CHAT_MODEL = os.getenv("FOUNDRY_CHAT_MODEL", "gpt-5.5")
# azure_ai.generate() sends temperature 0.2 and offers no way to override it, so
# the in-database panel needs a deployment that still accepts a temperature.
PG_CHAT_MODEL = os.getenv("FOUNDRY_PG_CHAT_MODEL", "gpt-4.1-mini")
EMBEDDING_MODEL = os.getenv("FOUNDRY_EMBEDDING_MODEL", "text-embedding-3-large")
EMBEDDING_SMALL_MODEL = os.getenv("FOUNDRY_EMBEDDING_SMALL_MODEL", "text-embedding-3-small")

COSMOS_ENDPOINT = os.environ["COSMOS_DB_ENDPOINT"]
COSMOS_DATABASE = os.getenv("COSMOS_DB_DATABASE", "ops-db")
COSMOS_CONTAINER = os.getenv("COSMOS_DB_CONTAINER", "tickets")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "ops-db")
POSTGRES_TABLE = os.getenv("POSTGRES_TABLE", "tickets")

COSMOS_DIMS = 3072
POSTGRES_DIMS = 1536

# Both stores use text-embedding-3-large. Only the width differs, and only
# because the index limits differ: Cosmos DiskANN takes the full 3072, pgvector
# stops at 2000. Same model both sides keeps the comparison honest, since any
# difference in results is then the database rather than the model.
COSMOS_MODEL = EMBEDDING_MODEL
POSTGRES_MODEL = EMBEDDING_MODEL

TOP_K = 5

# Scope for data-plane calls to Foundry. The token audience is Cognitive
# Services, not ARM, which is the usual reason a working az login still 401s.
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


def embedding_text(row: dict) -> str:
    """The text that becomes the vector.

    The error code is deliberately excluded. If codes were embedded, vector
    search could half-answer code lookups and the keyword panel would lose the
    contrast it exists to show.
    """
    parts = [row.get("title", ""), row.get("description", ""), row.get("resolution", "")]
    return "\n".join(p for p in parts if p)


def search_text(row: dict) -> str:
    """The text that gets keyword indexed. Includes the code, unlike the vector."""
    parts = [
        row.get("title", ""),
        row.get("description", ""),
        row.get("resolution", ""),
        row.get("error_code", ""),
    ]
    return " ".join(p for p in parts if p)
