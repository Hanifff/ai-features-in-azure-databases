"""Load the ticket dataset into Cosmos DB with embeddings.

Run this well before the event. Nothing here should ever run live: the room
should find the database already populated.

    python -m tools.load_cosmos --recreate
"""

from __future__ import annotations

import argparse
import concurrent.futures
import math
import sys
import time

import pandas as pd

from app import config, cosmos_store, foundry

EMBED_BATCH = 64
WRITE_WORKERS = 8


def to_document(row: dict) -> dict:
    resolved = row.get("resolved_hours")
    if resolved == "" or resolved is None or (isinstance(resolved, float) and math.isnan(resolved)):
        resolved = None
    return {
        "id": row["ticket_id"],
        "ticket_id": row["ticket_id"],
        "opened_at": row["opened_at"],
        "domain": row["domain"],
        "asset": row["asset"],
        "component": row["component"],
        "error_code": row["error_code"],
        "severity": row["severity"],
        "status": row["status"],
        "team": row["team"],
        "title": row["title"],
        "description": row["description"],
        "resolution": row.get("resolution") or "",
        "resolved_hours": float(resolved) if resolved is not None else None,
        "search_text": config.search_text(row),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true", help="drop and rebuild the container")
    args = parser.parse_args()

    frame = pd.read_csv(config.DATA_FILE, keep_default_na=False)
    rows = frame.to_dict(orient="records")
    print(f"{len(rows)} tickets from {config.DATA_FILE.name}")

    print(f"container {config.COSMOS_DATABASE}/{config.COSMOS_CONTAINER} ...", end=" ", flush=True)
    cosmos_store.create_container(recreate=args.recreate)
    cosmos_store.container.cache_clear()
    print("ready")

    texts = [config.embedding_text(row) for row in rows]
    vectors: list[list[float]] = []
    started = time.time()
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start : start + EMBED_BATCH]
        vectors.extend(foundry.embed(batch, config.COSMOS_DIMS))
        done = len(vectors)
        print(f"\r  embedding {done}/{len(texts)}", end="", flush=True)
    print(f"  ({time.time() - started:.0f}s, {config.COSMOS_DIMS} dims)")

    documents = []
    for row, vector in zip(rows, vectors):
        document = to_document(row)
        document["embedding"] = vector
        documents.append(document)

    # Autoscale absorbs the write burst, so there is no scale up and down to do.
    container = cosmos_store.container()
    written = 0
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=WRITE_WORKERS) as pool:
        futures = [pool.submit(container.upsert_item, doc) for doc in documents]
        for future in concurrent.futures.as_completed(futures):
            future.result()
            written += 1
            if written % 25 == 0 or written == len(documents):
                print(f"\r  writing {written}/{len(documents)}", end="", flush=True)
    print(f"  ({time.time() - started:.0f}s)")

    total = list(container.query_items("SELECT VALUE COUNT(1) FROM c", enable_cross_partition_query=True))[0]
    print(f"\ncontainer now holds {total} documents")
    if total != len(rows):
        print("WARNING: count does not match the source file", file=sys.stderr)


if __name__ == "__main__":
    main()
