"""PostgreSQL access: Entra token auth, and the queries that make the Postgres case.

The Cosmos panels show an application doing AI to its data. These panels show
the opposite: the database doing AI to itself. No vector crosses the wire in the
plain-English search, because PostgreSQL calls the embedding model directly with
its own managed identity.
"""

from __future__ import annotations

import functools
import json
import subprocess
import datetime
import decimal

import psycopg2
import psycopg2.extras

from . import config, foundry

PG_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

COLUMNS = (
    "ticket_id, opened_at, domain, asset, component, error_code, "
    "severity, status, team, title, description, resolution, resolved_hours"
)

# The same model Cosmos uses, truncated to the width pgvector's index allows.
# Passing dimensions keeps this a Matryoshka prefix of the 3072 vector rather
# than a different model, so the two databases are genuinely comparable.
EMBED_CALL = (
    f"azure_openai.create_embeddings('{config.POSTGRES_MODEL}', %s,"
    f" dimensions => {config.POSTGRES_DIMS})::vector"
)


@functools.lru_cache(maxsize=1)
def current_user_name() -> str:
    out = subprocess.run(
        ["az", "account", "show", "--query", "user.name", "-o", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def connect(database: str | None = None):
    """Password is a short-lived Entra token. There is no stored secret anywhere.

    The timeouts are not optional. Moving between networks leaves the old socket
    half-open: it still looks connected, and a query on it blocks forever. TCP
    keepalives turn that into an error the caller can recover from, in about
    twenty seconds rather than never.
    """
    token = foundry.credential().get_token(PG_SCOPE).token
    return psycopg2.connect(
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        dbname=database or config.POSTGRES_DB,
        user=current_user_name(),
        password=token,
        sslmode="require",
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=10,
        keepalives_interval=5,
        keepalives_count=2,
        # Longest honest query here is the in-database answer at about 3 s.
        options="-c statement_timeout=30000",
    )


# Opening a connection costs about 700 ms, most of it TLS and the token. Holding
# one open is the difference between a panel that feels live and one that does not.
_shared: dict = {"conn": None}


def _session():
    conn = _shared["conn"]
    if conn is not None and not conn.closed:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except psycopg2.Error:
            try:
                conn.close()
            except psycopg2.Error:
                pass
    _shared["conn"] = connect()
    return _shared["conn"]


def _clean(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def _fetch(sql: str, params: tuple = ()) -> list[dict]:
    conn = _session()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.commit()
        return [{k: _clean(v) for k, v in row.items()} for row in rows]
    except Exception:
        conn.rollback()
        raise


def _shown(sql: str, params: tuple) -> str:
    """The query with its parameters inlined, for display only.

    The whole point of the plain-English panel is that the audience can read the
    English sitting inside the SQL. A row of %s placeholders hides exactly the
    thing being demonstrated. Never execute this string.
    """
    for value in params:
        sql = sql.replace("%s", "'" + str(value).replace("'", "''") + "'", 1)
    return sql


def stats() -> dict:
    rows = _fetch(
        f"SELECT domain, count(*) AS n FROM {config.POSTGRES_TABLE} GROUP BY domain ORDER BY domain"
    )
    return {"total": sum(r["n"] for r in rows), "by_domain": rows}


def plain_english_search(question: str, top_k: int = config.TOP_K) -> tuple[list[dict], str]:
    """Panel P1. The query goes in as text. The database makes the vector.

    The embedding call sits in its own CTE so it happens once rather than once
    per reference, which also puts it on one readable line on screen.
    """
    sql = f"""WITH question AS (
    SELECT {EMBED_CALL} AS v
)
SELECT {COLUMNS},
       round((embedding <=> question.v)::numeric, 4) AS distance
FROM {config.POSTGRES_TABLE}, question
ORDER BY embedding <=> question.v
LIMIT {top_k}"""
    return _fetch(sql, (question,)), _shown(sql, (question,))


def semantic_aggregate(question: str, pool: int = 50) -> tuple[list[dict], str]:
    """Panel P2. A meaning search feeding a GROUP BY.

    This is the join a bolt-on vector store cannot do: the semantic result set
    is an ordinary relation, so ordinary SQL can aggregate over it.
    """
    sql = f"""WITH matches AS (
    SELECT ticket_id, domain, team, severity, resolved_hours
    FROM {config.POSTGRES_TABLE}
    ORDER BY embedding <=> {EMBED_CALL}
    LIMIT {pool}
)
SELECT domain,
       team,
       count(*)                                                AS tickets,
       round(avg(resolved_hours)::numeric, 1)                  AS avg_hours,
       count(*) FILTER (WHERE severity IN ('Critical','High')) AS urgent
FROM matches
GROUP BY domain, team
ORDER BY tickets DESC, avg_hours DESC"""
    return _fetch(sql, (question,)), _shown(sql, (question,))


def answer_in_sql(question: str, pool: int = 8) -> tuple[list[dict], str]:
    """Retrieval and reasoning in one statement, with no application tier.

    Cosmos did this too, but the orchestration lived in Python: embed, search,
    build a prompt, call the model. Here all four steps are the query, and the
    server authenticates to Foundry as itself.
    """
    sql = f"""WITH question AS (
    SELECT %s AS q
), asked AS (
    SELECT q, azure_openai.create_embeddings(
                  '{config.POSTGRES_MODEL}', q,
                  dimensions => {config.POSTGRES_DIMS})::vector AS v
    FROM question
), matches AS (
    SELECT ticket_id, title, description, resolution
    FROM {config.POSTGRES_TABLE}, asked
    WHERE resolution IS NOT NULL AND resolution <> ''
    ORDER BY embedding <=> asked.v
    LIMIT {pool}
), context AS (
    SELECT string_agg(ticket_id || ' | ' || title
                      || E'\\n  reported: ' || description
                      || E'\\n  fixed by:  ' || resolution, E'\\n') AS tickets
    FROM matches
)
SELECT azure_ai.generate(
           'Tickets from our system:' || E'\\n' || context.tickets
           || E'\\n\\nQuestion: ' || asked.q,
           model        => '{config.PG_CHAT_MODEL}',
           system_prompt => 'You are an operations support assistant. Answer in at '
                            'most 100 words, using only the tickets provided. Cite '
                            'the ticket IDs you relied on.'
       ) AS answer
FROM context, asked"""
    return _fetch(sql, (question,)), _shown(sql, (question,))


def tickets_exist(ticket_ids: list[str]) -> list[dict]:
    """Cited IDs checked against the table, so the claim is verified not asserted."""
    if not ticket_ids:
        return []
    found = {
        row["ticket_id"]
        for row in _fetch(
            f"SELECT ticket_id FROM {config.POSTGRES_TABLE} WHERE ticket_id = ANY(%s)",
            (ticket_ids,),
        )
    }
    return [{"ticket_id": t, "exists": t in found} for t in ticket_ids]


def explain(question: str, top_k: int = config.TOP_K) -> tuple[list[dict], str]:
    """Panel P2's back pocket, for the DBAs in the room.

    At 1,000 rows the planner costs a full scan below the DiskANN index startup
    and picks the scan. It is worth being the one who says so.
    """
    inner = f"""WITH question AS (
    SELECT {EMBED_CALL} AS v
)
SELECT ticket_id
FROM {config.POSTGRES_TABLE}, question
ORDER BY embedding <=> question.v
LIMIT {top_k}"""

    conn = _session()
    rows = []
    try:
        with conn.cursor() as cur:
            for label, setting in (("as it runs", None), ("seq scan disabled", "SET enable_seqscan = off")):
                if setting:
                    cur.execute(setting)
                cur.execute("EXPLAIN (ANALYZE) " + inner, (question,))
                lines = [r[0] for r in cur.fetchall()]
                scan = next((l.strip().lstrip("-> ") for l in lines if "Scan" in l), "")
                timing = next((l.split(":")[1].strip() for l in lines if "Execution Time" in l), "")
                rows.append({"plan": label, "access method": scan.split("  ")[0], "execution time": timing})
                if setting:
                    cur.execute("RESET ALL")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return rows, "EXPLAIN (ANALYZE)\n" + _shown(inner, (question,))


def hybrid_by_hand(question: str, top_k: int = config.TOP_K) -> tuple[list[dict], str]:
    """Panel P3. The fusion Cosmos does in one clause, written out by hand.

    It works, and it is a lot of SQL. The contrast is the point, not a criticism:
    here you own the ranking, which is also why you are free to change it.
    """
    prefix = "t." + COLUMNS.replace(", ", ", t.")
    sql = f"""WITH semantic AS (
    SELECT ticket_id,
           row_number() OVER (ORDER BY embedding <=> {EMBED_CALL}) AS rank
    FROM {config.POSTGRES_TABLE}
    LIMIT 50
),
lexical AS (
    SELECT ticket_id,
           row_number() OVER (
               ORDER BY ts_rank_cd(search_tsv, websearch_to_tsquery('english', %s)) DESC
           ) AS rank
    FROM {config.POSTGRES_TABLE}
    WHERE search_tsv @@ websearch_to_tsquery('english', %s)
    LIMIT 50
)
SELECT {prefix},
       round((coalesce(1.0/(60+s.rank), 0) + coalesce(1.0/(60+l.rank), 0))::numeric, 5) AS rrf
FROM {config.POSTGRES_TABLE} t
LEFT JOIN semantic s ON s.ticket_id = t.ticket_id
LEFT JOIN lexical  l ON l.ticket_id = t.ticket_id
WHERE s.ticket_id IS NOT NULL OR l.ticket_id IS NOT NULL
ORDER BY rrf DESC
LIMIT {top_k}"""
    return _fetch(sql, (question, question, question)), _shown(sql, (question, question, question))
