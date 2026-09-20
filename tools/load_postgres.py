"""Load the ticket dataset into PostgreSQL with embeddings, and wire up azure_ai.

Run this well before the event.

    python -m tools.load_postgres --recreate

The embeddings written here are generated client side, which is fast and easy to
retry. The demo point is not how the rows were embedded, it is that at query
time PostgreSQL calls the model itself, with its own managed identity, and the
application never handles a vector.
"""

from __future__ import annotations

import argparse
import math
import time

import pandas as pd
import psycopg2.extras

from app import config, foundry, postgres_store

EMBED_BATCH = 64

EXTENSIONS = ["vector", "pg_diskann", "azure_ai"]

SCHEMA = f"""
CREATE TABLE {config.POSTGRES_TABLE} (
    ticket_id     text PRIMARY KEY,
    opened_at     timestamptz,
    domain        text NOT NULL,
    asset         text,
    component     text,
    error_code    text,
    severity      text,
    status        text,
    team          text,
    title         text,
    description   text,
    resolution    text,
    resolved_hours double precision,
    search_text   text,
    search_tsv    tsvector GENERATED ALWAYS AS (to_tsvector('english', search_text)) STORED,
    embedding     vector({config.POSTGRES_DIMS})
);
"""

INDEXES = [
    f"CREATE INDEX ON {config.POSTGRES_TABLE} USING gin (search_tsv)",
    f"CREATE INDEX ON {config.POSTGRES_TABLE} (domain, severity)",
    # DiskANN rather than HNSW: it is the reason this server is General Purpose.
    f"CREATE INDEX ON {config.POSTGRES_TABLE} USING diskann (embedding vector_cosine_ops)",
]


def as_float(value) -> float | None:
    if value in ("", None):
        return None
    value = float(value)
    return None if math.isnan(value) else value


def configure_azure_ai(cur) -> None:
    endpoint = config.FOUNDRY_MODELS_ENDPOINT.rsplit("/models", 1)[0]
    endpoint = endpoint.replace(".services.ai.azure.com", ".openai.azure.com")
    cur.execute("SELECT azure_ai.set_setting('azure_openai.endpoint', %s)", (endpoint,))
    cur.execute("SELECT azure_ai.set_setting('azure_openai.auth_type', 'managed-identity')")
    cur.execute("SELECT azure_ai.get_setting('azure_openai.endpoint')")
    print(f"  azure_ai endpoint  {cur.fetchone()[0]}")
    cur.execute("SELECT azure_ai.get_setting('azure_openai.auth_type')")
    print(f"  azure_ai auth      {cur.fetchone()[0]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true", help="drop and rebuild the table")
    args = parser.parse_args()

    frame = pd.read_csv(config.DATA_FILE, keep_default_na=False)
    rows = frame.to_dict(orient="records")
    print(f"{len(rows)} tickets from {config.DATA_FILE.name}")

    conn = postgres_store.connect()
    conn.autocommit = True
    cur = conn.cursor()

    for extension in EXTENSIONS:
        cur.execute(f"CREATE EXTENSION IF NOT EXISTS {extension} CASCADE")
    print(f"  extensions         {', '.join(EXTENSIONS)}")
    configure_azure_ai(cur)

    cur.execute(
        "SELECT array_length(azure_openai.create_embeddings(%s, 'connectivity check', dimensions => %s), 1)",
        (config.POSTGRES_MODEL, config.POSTGRES_DIMS),
    )
    print(f"  model reachable    {config.POSTGRES_MODEL}, {cur.fetchone()[0]} dims")

    if args.recreate:
        cur.execute(f"DROP TABLE IF EXISTS {config.POSTGRES_TABLE}")
    cur.execute(f"SELECT to_regclass('{config.POSTGRES_TABLE}')")
    if cur.fetchone()[0] is None:
        cur.execute(SCHEMA)
        print(f"  table              {config.POSTGRES_TABLE} created")

    texts = [config.embedding_text(row) for row in rows]
    vectors: list[list[float]] = []
    started = time.time()
    for start in range(0, len(texts), EMBED_BATCH):
        vectors.extend(foundry.embed(texts[start : start + EMBED_BATCH], config.POSTGRES_DIMS))
        print(f"\r  embedding {len(vectors)}/{len(texts)}", end="", flush=True)
    print(f"  ({time.time() - started:.0f}s, {config.POSTGRES_DIMS} dims)")

    payload = [
        (
            row["ticket_id"],
            row["opened_at"],
            row["domain"],
            row["asset"],
            row["component"],
            row["error_code"],
            row["severity"],
            row["status"],
            row["team"],
            row["title"],
            row["description"],
            row.get("resolution") or "",
            as_float(row.get("resolved_hours")),
            config.search_text(row),
            "[" + ",".join(f"{v:.7f}" for v in vector) + "]",
        )
        for row, vector in zip(rows, vectors)
    ]

    started = time.time()
    psycopg2.extras.execute_values(
        cur,
        f"""INSERT INTO {config.POSTGRES_TABLE}
            (ticket_id, opened_at, domain, asset, component, error_code, severity,
             status, team, title, description, resolution, resolved_hours,
             search_text, embedding)
            VALUES %s
            ON CONFLICT (ticket_id) DO UPDATE SET embedding = EXCLUDED.embedding""",
        payload,
        page_size=100,
    )
    print(f"  inserted {len(payload)} rows ({time.time() - started:.0f}s)")

    started = time.time()
    for statement in INDEXES:
        cur.execute(statement)
    print(f"  indexes built ({time.time() - started:.0f}s)")

    cur.execute(f"SELECT count(*) FROM {config.POSTGRES_TABLE}")
    print(f"\ntable now holds {cur.fetchone()[0]} rows")
    conn.close()


if __name__ == "__main__":
    main()
