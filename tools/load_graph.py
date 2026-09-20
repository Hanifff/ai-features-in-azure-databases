"""Build the Apache AGE graph from the tickets table.

    python -m tools.load_graph --recreate

The graph deliberately holds no text and no vectors. Search already does text
well, and repeating it here would invite a comparison that misses the point.
What the graph holds is the shape of the estate: which asset a ticket was raised
against, which team resolved it, and which fault code it carried. That shape is
what lets a single symptom become a list of other assets worth inspecting.
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

from app import config, graph_store, postgres_store

BATCH = 100

# Only tickets whose nearest neighbour carries a different fault code earn a
# SIMILAR_TO edge. A same-code neighbour adds nothing, because CODED already
# links those two. The threshold keeps the bridge to pairs that genuinely read
# alike: cross-code distances run from 0.31 to 0.63 on this dataset.
SIMILAR_MAX_DISTANCE = 0.40
SIMILAR_PER_TICKET = 2


def similar_tickets() -> dict[str, list[str]]:
    """The one edge no foreign key could produce, computed from the embeddings."""
    rows = postgres_store._fetch(
        """
        SELECT t.ticket_id AS src, n.ticket_id AS dst
        FROM tickets t
        CROSS JOIN LATERAL (
            SELECT o.ticket_id
            FROM tickets o
            WHERE o.ticket_id <> t.ticket_id
              AND o.error_code <> t.error_code
              AND o.embedding <=> t.embedding < %s
            ORDER BY o.embedding <=> t.embedding
            LIMIT %s
        ) n
        """,
        (SIMILAR_MAX_DISTANCE, SIMILAR_PER_TICKET),
    )
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["src"], []).append(row["dst"])
    return out


def esc(value) -> str:
    return str(value).replace("\\", "").replace("'", "\\'")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true", help="drop and rebuild the graph")
    args = parser.parse_args()

    rows = pd.read_csv(config.DATA_FILE, keep_default_na=False).to_dict(orient="records")
    print(f"{len(rows)} tickets from {config.DATA_FILE.name}")

    neighbours = similar_tickets()
    print(f"  {sum(len(v) for v in neighbours.values())} semantic links from the embeddings")

    conn = postgres_store.connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS age CASCADE")
    cur.execute(graph_store.SEARCH_PATH)

    if args.recreate:
        cur.execute(
            "SELECT drop_graph(%s, true) WHERE EXISTS "
            "(SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s)",
            (graph_store.GRAPH, graph_store.GRAPH),
        )
    cur.execute("SELECT count(*) FROM ag_catalog.ag_graph WHERE name = %s", (graph_store.GRAPH,))
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT create_graph(%s)", (graph_store.GRAPH,))
        print(f"  graph '{graph_store.GRAPH}' created")

    def run(cypher: str, expect: str = "v agtype") -> None:
        cur.execute(f"SELECT * FROM cypher('{graph_store.GRAPH}', $$ {cypher} $$) AS ({expect})")

    started = time.time()

    assets = {(r["asset"], r["domain"]) for r in rows}
    teams = {(r["team"], r["domain"]) for r in rows}
    codes = {(r["error_code"], r["component"], r["domain"]) for r in rows}

    for name, domain in assets:
        run(f"CREATE (:Asset {{name:'{esc(name)}', domain:'{esc(domain)}'}})")
    for name, domain in teams:
        run(f"CREATE (:Team {{name:'{esc(name)}', domain:'{esc(domain)}'}})")
    for code, component, domain in codes:
        run(f"CREATE (:Code {{code:'{esc(code)}', component:'{esc(component)}', domain:'{esc(domain)}'}})")
    print(f"  {len(assets)} assets, {len(teams)} teams, {len(codes)} codes")

    for start in range(0, len(rows), BATCH):
        creates = []
        for r in rows[start : start + BATCH]:
            hours = r.get("resolved_hours")
            # Omit hours entirely when the ticket is still open. A zero would be
            # averaged in and quietly report an unfixed fault as instant to fix.
            hours_prop = f", hours:{float(hours)}" if hours not in ("", None) else ""
            sims = neighbours.get(r["ticket_id"], [])
            sim_props = "".join(
                f", sim{i}:'{esc(s)}'" for i, s in enumerate(sims[:SIMILAR_PER_TICKET], start=1)
            )
            creates.append(
                f"(:Ticket {{id:'{esc(r['ticket_id'])}', asset:'{esc(r['asset'])}', "
                f"team:'{esc(r['team'])}', code:'{esc(r['error_code'])}', "
                f"severity:'{esc(r['severity'])}', status:'{esc(r['status'])}'"
                f"{hours_prop}{sim_props}}})"
            )
        run("CREATE " + ", ".join(creates))
        print(f"\r  tickets {min(start + BATCH, len(rows))}/{len(rows)}", end="", flush=True)
    print()

    # Edges in bulk. Matching on the property each Ticket already carries is far
    # cheaper than a MATCH per row, and the property is dropped afterwards.
    for label, key, target, prop in [
        ("ON", "asset", "Asset", "name"),
        ("BY", "team", "Team", "name"),
        ("CODED", "code", "Code", "code"),
    ]:
        run(
            f"MATCH (t:Ticket), (n:{target}) WHERE t.{key} = n.{prop} "
            f"CREATE (t)-[:{label}]->(n)"
        )
        print(f"  edges :{label}")

    # Ticket to Ticket, by meaning. Every other edge here restates a column that
    # was already in the table; this one could not be written as a JOIN.
    for i in range(1, SIMILAR_PER_TICKET + 1):
        run(
            f"MATCH (a:Ticket), (b:Ticket) WHERE a.sim{i} = b.id "
            f"CREATE (a)-[:SIMILAR_TO]->(b)"
        )
    print("  edges :SIMILAR_TO")

    print(f"\nbuilt in {time.time() - started:.0f}s")
    for label in ("Asset", "Team", "Code", "Ticket"):
        cur.execute(
            f"SELECT count(*) FROM cypher('{graph_store.GRAPH}', "
            f"$$ MATCH (n:{label}) RETURN n $$) AS (v agtype)"
        )
        print(f"  {label:<8} {cur.fetchone()[0]}")
    cur.execute(
        f"SELECT count(*) FROM cypher('{graph_store.GRAPH}', "
        f"$$ MATCH ()-[r]->() RETURN r $$) AS (v agtype)"
    )
    print(f"  edges    {cur.fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()
