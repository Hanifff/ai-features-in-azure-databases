"""Apache AGE graph queries, and the layout for drawing them.

The graph exists to answer a question search cannot: not "has this happened
before", which vector search already answers well, but "which other assets
should I go and look at". Those assets were never in any search result, because
nothing about their tickets resembles the question that was asked.
"""

from __future__ import annotations

import json
import math

from . import config, postgres_store

GRAPH = "ops"
SEARCH_PATH = 'SET search_path = ag_catalog, "$user", public'


def _cypher(cur, query: str, columns: str):
    cur.execute(SEARCH_PATH)
    cur.execute(f"SELECT * FROM cypher('{GRAPH}', $$ {query} $$) AS ({columns})")
    return cur.fetchall()


def _value(raw):
    """AGE returns agtype, which is JSON with the quoting left on."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def expand(question: str, seed_k: int = 3) -> dict:
    """Vector search for the seed tickets, then walk the graph out from them.

    The seed comes from PostgreSQL's own embedding call, so this is the previous
    panel's result being used as a starting point rather than a separate demo.

    Only three seeds, deliberately. That is what a person would actually read,
    and it leaves the graph something to add. Matching every seed at once also
    multiplies the counts, because each ticket is reached once per seed, so the
    fault code is taken from the seeds and the graph query starts from that.
    """
    seeds, seed_sql = postgres_store.plain_english_search(question, seed_k)
    if not seeds:
        return {"code": None, "seeds": [], "assets": [], "new_assets": [], "cypher": "", "layout": None}

    code = seeds[0]["error_code"]
    seed_assets = {s["asset"] for s in seeds}

    # Walk one: the fault code's own tickets. Honest disclosure, this is exactly
    # a SELECT DISTINCT asset WHERE error_code = ... and a DBA will say so.
    by_code_cypher = f"""MATCH (c:Code {{code: '{code}'}})<-[:CODED]-(t:Ticket)-[:ON]->(a:Asset)
RETURN a.name, a.domain, count(t), avg(t.hours)"""

    # Walk two: across the SIMILAR_TO edge, which was derived from the embeddings
    # and exists in no column. This is the half that no WHERE clause can reach.
    by_meaning_cypher = f"""MATCH (c:Code {{code: '{code}'}})<-[:CODED]-(:Ticket)
      -[:SIMILAR_TO]->(t:Ticket)-[:ON]->(a:Asset)
RETURN a.name, a.domain, count(t), avg(t.hours)"""

    conn = postgres_store._session()
    try:
        with conn.cursor() as cur:
            columns = "asset agtype, domain agtype, tickets agtype, avg_hours agtype"
            code_rows = _cypher(cur, by_code_cypher, columns)
            meaning_rows = _cypher(cur, by_meaning_cypher, columns)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    assets: dict[str, dict] = {}
    for rows, route in ((code_rows, "code"), (meaning_rows, "meaning")):
        for asset_v, domain_v, tickets_v, hours_v in rows:
            name = _value(asset_v)
            hours = _value(hours_v)
            entry = assets.setdefault(name, {
                "asset": name,
                "domain": _value(domain_v),
                "tickets": 0,
                "avg_hours": None,
                "in_search": name in seed_assets,
                "routes": set(),
            })
            entry["routes"].add(route)
            if route == "code":
                entry["tickets"] = int(_value(tickets_v) or 0)
                # None when every ticket on this asset is still open.
                entry["avg_hours"] = round(float(hours), 1) if hours is not None else None
            else:
                entry["related"] = int(_value(tickets_v) or 0)
                entry["related_hours"] = round(float(hours), 1) if hours is not None else None

    ordered = []
    for entry in assets.values():
        routes = entry.pop("routes")
        entry["by_code"] = "code" in routes
        # The payoff: reached only by an edge that was computed, not declared.
        entry["by_meaning_only"] = routes == {"meaning"}
        entry.setdefault("related", 0)
        # A meaning-only asset has no ticket with this code, so its hours have to
        # come from the similar tickets the edge actually reached.
        if entry["avg_hours"] is None:
            entry["avg_hours"] = entry.get("related_hours")
        entry.pop("related_hours", None)
        ordered.append(entry)
    ordered.sort(key=lambda a: (a["by_meaning_only"], -a["tickets"], a["asset"]))

    return {
        "code": code,
        "seeds": seeds,
        "seed_sql": seed_sql,
        "assets": ordered,
        "new_assets": [a for a in ordered if not a["in_search"]],
        "meaning_only": [a for a in ordered if a["by_meaning_only"]],
        "cypher": by_code_cypher + "\n\n" + by_meaning_cypher,
        "layout": _layout(code, ordered),
    }


def _layout(code: str, assets: list[dict], width: int = 1100, height: int = 460) -> dict:
    """Radial layout computed here so the page needs no drawing library.

    A CDN dependency is a bad trade for a demo that has to survive a venue
    network, and a fixed layout is also steadier on screen than a force
    simulation that settles differently every run.
    """
    cx, cy = width / 2, height / 2
    nodes = [{"id": code, "label": code, "kind": "code", "x": cx, "y": cy, "r": 42}]
    edges = []

    count = max(len(assets), 1)
    radius_x, radius_y = width / 2 - 130, height / 2 - 70
    for i, asset in enumerate(assets):
        angle = -math.pi / 2 + (2 * math.pi * i / count)
        if asset["by_meaning_only"]:
            kind = "meaning"
        elif asset["in_search"]:
            kind = "found"
        else:
            kind = "new"
        node = {
            "id": asset["asset"],
            "label": asset["asset"],
            "kind": kind,
            "x": cx + radius_x * math.cos(angle),
            "y": cy + radius_y * math.sin(angle),
            "r": 18 + min(max(asset["tickets"], asset.get("related", 0)), 18),
            "tickets": asset["tickets"] or asset.get("related", 0),
        }
        nodes.append(node)
        edges.append({"from": code, "to": asset["asset"], "kind": kind})
    return {"width": width, "height": height, "nodes": nodes, "edges": edges}


def code_map(width: int = 1100, height: int = 520) -> dict:
    """Every fault code, and the semantic links between them.

    The expand() diagram is a star because it is one question's answer. This is
    the whole graph at a level a projector can actually show: twelve fault types
    and the pairs the embeddings say describe the same failure. The links that
    cross a domain boundary are the ones worth pointing at.
    """
    nodes_cypher = """MATCH (c:Code)<-[:CODED]-(t:Ticket)
RETURN c.code, c.component, c.domain, count(t)"""

    edges_cypher = """MATCH (c1:Code)<-[:CODED]-(:Ticket)
      -[:SIMILAR_TO]->(:Ticket)-[:CODED]->(c2:Code)
RETURN c1.code, c2.code, count(*)"""

    conn = postgres_store._session()
    try:
        with conn.cursor() as cur:
            raw_nodes = _cypher(cur, nodes_cypher,
                                "code agtype, component agtype, domain agtype, tickets agtype")
            raw_edges = _cypher(cur, edges_cypher, "a agtype, b agtype, n agtype")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    codes = {}
    for code_v, component_v, domain_v, tickets_v in raw_nodes:
        code = _value(code_v)
        codes[code] = {
            "code": code,
            "component": _value(component_v),
            "domain": _value(domain_v),
            "tickets": int(_value(tickets_v) or 0),
        }

    # A resembles B and B resembles A are the same line on screen.
    pairs: dict[tuple[str, str], int] = {}
    for a_v, b_v, n_v in raw_edges:
        a, b = _value(a_v), _value(b_v)
        if a == b:
            continue
        key = (a, b) if a < b else (b, a)
        pairs[key] = pairs.get(key, 0) + int(_value(n_v) or 0)

    ordered = sorted(codes.values(), key=lambda c: (c["domain"], c["code"]))
    cx, cy = width / 2, height / 2
    radius_x, radius_y = width / 2 - 150, height / 2 - 80
    placed = {}
    for i, entry in enumerate(ordered):
        angle = -math.pi / 2 + (2 * math.pi * i / max(len(ordered), 1))
        entry = dict(entry)
        entry["x"] = cx + radius_x * math.cos(angle)
        entry["y"] = cy + radius_y * math.sin(angle)
        entry["r"] = 16 + min(entry["tickets"] / 6, 22)
        placed[entry["code"]] = entry

    edges = []
    for (a, b), weight in sorted(pairs.items(), key=lambda kv: -kv[1]):
        if a not in placed or b not in placed:
            continue
        edges.append({
            "from": a,
            "to": b,
            "weight": weight,
            "crosses": placed[a]["domain"] != placed[b]["domain"],
            "x1": placed[a]["x"], "y1": placed[a]["y"],
            "x2": placed[b]["x"], "y2": placed[b]["y"],
        })

    linked = {c for edge in edges for c in (edge["from"], edge["to"])}
    for entry in placed.values():
        entry["linked"] = entry["code"] in linked

    return {
        "width": width,
        "height": height,
        "nodes": list(placed.values()),
        "edges": edges,
        "crossing": sum(1 for e in edges if e["crosses"]),
        "domains": sorted({e["domain"] for e in placed.values()}),
        "cypher": edges_cypher,
    }


def stats() -> dict:
    conn = postgres_store._session()
    try:
        with conn.cursor() as cur:
            counts = {}
            for label in ("Asset", "Team", "Code", "Ticket"):
                rows = _cypher(cur, f"MATCH (n:{label}) RETURN count(n)", "n agtype")
                counts[label.lower()] = int(_value(rows[0][0]) or 0)
            rows = _cypher(cur, "MATCH ()-[r]->() RETURN count(r)", "n agtype")
            counts["edges"] = int(_value(rows[0][0]) or 0)
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        return {}
