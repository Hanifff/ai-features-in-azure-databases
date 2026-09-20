"""Cosmos DB NoSQL access: provisioning, and the four search strategies.

Every search function returns (rows, sql) so the UI can show the query that
actually ran. Nothing on screen is a screenshot of a query we did not execute.
"""

from __future__ import annotations

import functools

from azure.cosmos import CosmosClient, PartitionKey, ThroughputProperties

from . import config, foundry

# The container is created here rather than in Terraform, so its throughput
# lives here too. Autoscale rather than manual, because the demo is idle almost
# all of the time and then bursts, and a bulk reload of 40 KB documents would
# otherwise need a manual scale up and back down.
#
# Autoscale bills a floor of ten percent of the ceiling, so this number is a
# standing cost, not just a limit. Measured cost is 4 to 9 RU for most queries
# and about 70 for hybrid RRF, so 5000 is roughly seventy hybrid queries per
# second: far more than a demo needs, and still an order of magnitude below what
# the PostgreSQL server costs while it is running.
#
# Cosmos will not let the ceiling drop below a tenth of the highest value ever
# provisioned, so this cannot be lowered past 2000 now.
AUTOSCALE_MAX_RU = 5000

PROJECTION = (
    "c.ticket_id, c.opened_at, c.domain, c.asset, c.component, c.error_code, "
    "c.severity, c.status, c.team, c.title, c.description, c.resolution, c.resolved_hours"
)

VECTOR_EMBEDDING_POLICY = {
    "vectorEmbeddings": [
        {
            "path": "/embedding",
            "dataType": "float32",
            "distanceFunction": "cosine",
            "dimensions": config.COSMOS_DIMS,
        }
    ]
}

FULL_TEXT_POLICY = {
    "defaultLanguage": "en-US",
    "fullTextPaths": [{"path": "/search_text", "language": "en-US"}],
}

INDEXING_POLICY = {
    "indexingMode": "consistent",
    "automatic": True,
    "includedPaths": [{"path": "/*"}],
    # The raw vector is excluded from the normal index: it is served by the
    # DiskANN index below, and indexing 3072 floats per document is pure cost.
    "excludedPaths": [{"path": "/embedding/*"}, {"path": "/_etag/?"}],
    "vectorIndexes": [{"path": "/embedding", "type": "diskANN"}],
    "fullTextIndexes": [{"path": "/search_text"}],
}


@functools.lru_cache(maxsize=1)
def client() -> CosmosClient:
    # A ticket document carries 3072 floats, so bulk writes throttle easily.
    # Letting the SDK absorb 429s is correct: they are flow control, not errors.
    return CosmosClient(
        config.COSMOS_ENDPOINT,
        credential=foundry.credential(),
        retry_total=40,
        retry_backoff_max=30,
    )


@functools.lru_cache(maxsize=1)
def container():
    return client().get_database_client(config.COSMOS_DATABASE).get_container_client(
        config.COSMOS_CONTAINER
    )


def create_container(recreate: bool = False):
    database = client().get_database_client(config.COSMOS_DATABASE)
    if recreate:
        try:
            database.delete_container(config.COSMOS_CONTAINER)
        except Exception:
            pass
    return database.create_container_if_not_exists(
        id=config.COSMOS_CONTAINER,
        partition_key=PartitionKey(path="/domain"),
        indexing_policy=INDEXING_POLICY,
        vector_embedding_policy=VECTOR_EMBEDDING_POLICY,
        full_text_policy=FULL_TEXT_POLICY,
        offer_throughput=ThroughputProperties(auto_scale_max_throughput=AUTOSCALE_MAX_RU),
    )


def _run(sql: str, params: list[dict]) -> list[dict]:
    return list(
        container().query_items(query=sql, parameters=params, enable_cross_partition_query=True)
    )


def stats() -> dict:
    """Read at page load so the count on screen comes from the database."""
    total = _run("SELECT VALUE COUNT(1) FROM c", [])[0]
    # One count per domain rather than GROUP BY: the SDK rejects a non-value
    # aggregate with GROUP BY, and four cheap counts are not worth working around.
    domains = sorted(_run("SELECT DISTINCT VALUE c.domain FROM c", []))
    by_domain = [
        {
            "domain": domain,
            "n": _run(
                "SELECT VALUE COUNT(1) FROM c WHERE c.domain = @d",
                [{"name": "@d", "value": domain}],
            )[0],
        }
        for domain in domains
    ]
    sample = _run(f"SELECT TOP 1 {PROJECTION} FROM c ORDER BY c.ticket_id", [])
    return {"total": total, "by_domain": by_domain, "sample": sample[0] if sample else None}


def keyword_search(term: str, top_k: int = config.TOP_K) -> tuple[list[dict], str]:
    """Literal matching against the full-text index.

    This is what an operations engineer actually does: paste the code in and
    look. It finds an exact code perfectly and a paraphrased symptom not at all.

    Deliberately the same index hybrid search fuses later, so panel 4 is adding
    vectors to this exact behaviour rather than to a different engine.
    """
    sql = (
        f"SELECT TOP @k {PROJECTION}\n"
        "FROM c\n"
        "WHERE FullTextContains(c.search_text, @term)"
    )
    rows = _run(sql, [{"name": "@term", "value": term}, {"name": "@k", "value": top_k}])
    return rows, sql


def keyword_count(term: str) -> int:
    """How many tickets actually match, as opposed to how many are shown."""
    return _run(
        "SELECT VALUE COUNT(1) FROM c WHERE FullTextContains(c.search_text, @term)",
        [{"name": "@term", "value": term}],
    )[0]


def vector_search(query: str, top_k: int = config.TOP_K) -> tuple[list[dict], str]:
    vector = foundry.embed_one(query, config.COSMOS_DIMS)
    sql = (
        f"SELECT TOP @k {PROJECTION},\n"
        "       VectorDistance(c.embedding, @vec) AS score\n"
        "FROM c\n"
        "ORDER BY VectorDistance(c.embedding, @vec)"
    )
    rows = _run(sql, [{"name": "@vec", "value": vector}, {"name": "@k", "value": top_k}])
    return rows, sql


def filtered_vector_search(
    query: str,
    severity: str | None = None,
    domain: str | None = None,
    resolved_only: bool = False,
    top_k: int = config.TOP_K,
) -> tuple[list[dict], str]:
    """Meaning and metadata in one request, evaluated by the same engine."""
    vector = foundry.embed_one(query, config.COSMOS_DIMS)
    params = [{"name": "@vec", "value": vector}, {"name": "@k", "value": top_k}]
    clauses = []
    if severity:
        clauses.append("c.severity = @severity")
        params.append({"name": "@severity", "value": severity})
    if domain:
        clauses.append("c.domain = @domain")
        params.append({"name": "@domain", "value": domain})
    if resolved_only:
        # Asking what fixed it only makes sense against tickets that were fixed.
        clauses.append("c.resolution != ''")
    where = f"WHERE {' AND '.join(clauses)}\n" if clauses else ""

    sql = (
        f"SELECT TOP @k {PROJECTION},\n"
        "       VectorDistance(c.embedding, @vec) AS score\n"
        "FROM c\n"
        f"{where}"
        "ORDER BY VectorDistance(c.embedding, @vec)"
    )
    return _run(sql, params), sql


def hybrid_search(query: str, top_k: int = config.TOP_K) -> tuple[list[dict], str]:
    """One clause, both strategies, fused by the engine with RRF.

    Show the rank, not the RRF score. The score is an artefact of the fusion
    constant and inviting the room to interpret it wastes a minute.
    """
    vector = foundry.embed_one(query, config.COSMOS_DIMS)
    sql = (
        f"SELECT TOP @k {PROJECTION}\n"
        "FROM c\n"
        "ORDER BY RANK RRF(\n"
        "    FullTextScore(c.search_text, @term),\n"
        "    VectorDistance(c.embedding, @vec)\n"
        ")"
    )
    params = [
        {"name": "@term", "value": query},
        {"name": "@vec", "value": vector},
        {"name": "@k", "value": top_k},
    ]
    rows = _run(sql, params)
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows, sql


def facets() -> dict:
    severities = _run("SELECT DISTINCT VALUE c.severity FROM c", [])
    domains = _run("SELECT DISTINCT VALUE c.domain FROM c", [])
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    return {
        "severities": sorted(severities, key=lambda s: order.get(s, 9)),
        "domains": sorted(domains),
    }
