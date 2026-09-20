"""Flask app for the demo.

Every panel does the same three things: run a real query against a real service,
show the rows, and show the query that produced them. Nothing is precomputed and
nothing is faked, because the first question from the room is always whether it
is faked.

    python -m app.app
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from flask import Flask, jsonify, render_template, request

from . import config, cosmos_store, foundry, graph_store, grounding, postgres_store, queries

app = Flask(__name__)
app.json.sort_keys = False
# Jinja caches templates whenever debug is off, which means edits appear to do
# nothing until the server is restarted. Not worth the confusion for one demo.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


def timed(fn, *args, **kwargs):
    started = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, int((time.perf_counter() - started) * 1000)


def payload(rows, sql, ms, panel=None, value=None, extra=None):
    body = {
        "rows": rows,
        "sql": sql,
        "ms": ms,
        "count": len(rows),
        "note": queries.note_for(panel, value) if panel else "",
    }
    if extra:
        body.update(extra)
    return jsonify(body)


def fail(exc: Exception):
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/")
def overview_page():
    """The estate, before any of the demos. Everything counted live."""
    context = {
        "page": "overview",
        "title": "AI features in Azure databases",
        "subtitle": "One dataset, three stores, one Foundry account. Every number on this page was read live.",
        "config": config,
        "stats": None,
        "pg_stats": None,
        "graph_stats": None,
        "error": None,
    }
    problems = []
    for key, fn, label in (
        ("stats", cosmos_store.stats, "Cosmos DB"),
        ("pg_stats", postgres_store.stats, "PostgreSQL"),
        ("graph_stats", graph_store.stats, "the graph"),
    ):
        try:
            context[key] = fn()
        except Exception as exc:
            problems.append(f"{label}: {type(exc).__name__}")
    if problems:
        context["error"] = "Not reachable: " + ", ".join(problems)
    return render_template("overview.html", **context)


@app.route("/cosmos")
def cosmos_page():
    context = {
        "page": "cosmos",
        "title": "Azure Cosmos DB for NoSQL",
        "subtitle": "Your application does AI to your data. Every result below is a live query.",
        "catalogue": queries.CATALOGUE,
        "config": config,
        "facets": {"severities": [], "domains": []},
        "error": None,
    }
    try:
        context["facets"] = cosmos_store.facets()
    except Exception as exc:
        context["error"] = f"Cosmos DB is not reachable: {type(exc).__name__}: {exc}"
    return render_template("cosmos.html", **context)


@app.route("/postgres")
def postgres_page():
    context = {
        "page": "postgres",
        "title": "Azure Database for PostgreSQL",
        "subtitle": "Your data does AI to itself. The same tickets, a different idea.",
        "catalogue": queries.CATALOGUE,
        "config": config,
        "stats": None,
        "error": None,
    }
    try:
        context["stats"] = postgres_store.stats()
    except Exception as exc:
        context["error"] = f"PostgreSQL is not reachable: {type(exc).__name__}: {exc}"
    return render_template("postgres.html", **context)


@app.route("/graph")
def graph_page():
    return render_template(
        "graph.html",
        page="graph",
        title="The graph, in the same PostgreSQL server",
        subtitle="Search returns tickets. The graph returns the assets you should go and look at.",
        catalogue=queries.CATALOGUE,
        config=config,
        error=None,
    )


@app.post("/api/graph")
def api_graph():
    question = request.json.get("q", "")
    try:
        result, ms = timed(graph_store.expand, question)
        result["ms"] = ms
        result["note"] = queries.note_for("graph", question)
        return jsonify(result)
    except Exception as exc:
        return fail(exc)


@app.post("/api/embed")
def api_embed():
    """Panel 2. One live embedding, so the corpus vectors are not taken on trust."""
    text = request.json.get("text", "")
    try:
        (vector,), ms = timed(foundry.embed, [text], config.COSMOS_DIMS)
        return jsonify(
            {
                "ms": ms,
                "model": config.EMBEDDING_MODEL,
                "dims": len(vector),
                "head": [round(v, 6) for v in vector[:12]],
                "text": text,
            }
        )
    except Exception as exc:
        return fail(exc)


@app.post("/api/keyword")
def api_keyword():
    term = request.json.get("q", "")
    try:
        (result, ms) = timed(cosmos_store.keyword_search, term)
        rows, sql = result
        total = cosmos_store.keyword_count(term)
        return payload(rows, sql, ms, "keyword", term, {"total_matches": total})
    except Exception as exc:
        return fail(exc)


@app.post("/api/vector")
def api_vector():
    query = request.json.get("q", "")
    try:
        (result, ms) = timed(cosmos_store.vector_search, query)
        rows, sql = result
        return payload(rows, sql, ms, "vector", query)
    except Exception as exc:
        return fail(exc)


@app.post("/api/filtered")
def api_filtered():
    body = request.json
    try:
        (result, ms) = timed(
            cosmos_store.filtered_vector_search,
            body.get("q", ""),
            body.get("severity") or None,
            body.get("domain") or None,
        )
        rows, sql = result
        return payload(rows, sql, ms, "filtered", body.get("q", ""))
    except Exception as exc:
        return fail(exc)


@app.post("/api/hybrid")
def api_hybrid():
    query = request.json.get("q", "")
    try:
        (result, ms) = timed(cosmos_store.hybrid_search, query)
        rows, sql = result
        return payload(rows, sql, ms, "hybrid", query)
    except Exception as exc:
        return fail(exc)


@app.post("/api/grounded")
def api_grounded():
    question = request.json.get("q", "")
    try:
        result, ms = timed(grounding.compare, question)
        result["ms"] = ms
        result["note"] = queries.note_for("grounded", question)
        return jsonify(result)
    except Exception as exc:
        return fail(exc)


@app.post("/api/pg/search")
def api_pg_search():
    question = request.json.get("q", "")
    try:
        (result, ms) = timed(postgres_store.plain_english_search, question)
        rows, sql = result
        return payload(rows, sql, ms, "postgres", question)
    except Exception as exc:
        return fail(exc)


@app.post("/api/pg/aggregate")
def api_pg_aggregate():
    question = request.json.get("q", "")
    try:
        (result, ms) = timed(postgres_store.semantic_aggregate, question)
        rows, sql = result
        return payload(rows, sql, ms)
    except Exception as exc:
        return fail(exc)


@app.post("/api/pg/answer")
def api_pg_answer():
    question = request.json.get("q", "")
    try:
        (result, ms) = timed(postgres_store.answer_in_sql, question)
        rows, sql = result
        answer = rows[0]["answer"] if rows else ""
        return jsonify(
            {
                "answer": answer,
                "citations": postgres_store.tickets_exist(
                    list(dict.fromkeys(grounding.TICKET_ID.findall(answer)))
                ),
                "sql": sql,
                "ms": ms,
                "model": config.PG_CHAT_MODEL,
            }
        )
    except Exception as exc:
        return fail(exc)


@app.post("/api/pg/explain")
def api_pg_explain():
    question = request.json.get("q", "")
    try:
        (result, ms) = timed(postgres_store.explain, question)
        rows, sql = result
        return payload(rows, sql, ms, extra={
            "note": "The index is built and it works. At 1,000 rows the planner costs a "
                    "full scan below the DiskANN index startup, so it picks the scan. "
                    "Force the index and it is still faster, which is the planner's cost "
                    "model being conservative at small scale, not a broken index. At "
                    "millions of rows there is no contest."
        })
    except Exception as exc:
        return fail(exc)


@app.post("/api/pg/hybrid")
def api_pg_hybrid():
    question = request.json.get("q", "")
    try:
        (result, ms) = timed(postgres_store.hybrid_by_hand, question)
        rows, sql = result
        return payload(rows, sql, ms)
    except Exception as exc:
        return fail(exc)


@app.get("/api/models")
def api_models():
    """Read the deployments live. A slide of model names proves nothing."""
    try:
        out = subprocess.run(
            [
                "az", "cognitiveservices", "account", "deployment", "list",
                "-g", config.RESOURCE_GROUP,
                "-n", config.FOUNDRY_ACCOUNT,
                "-o", "json",
            ],
            capture_output=True, text=True, check=True,
        )
        deployments = [
            {
                "name": d["name"],
                "model": d["properties"]["model"]["name"],
                "version": d["properties"]["model"]["version"],
            }
            for d in json.loads(out.stdout)
        ]
        return jsonify({"deployments": sorted(deployments, key=lambda d: d["name"])})
    except Exception as exc:
        return fail(exc)


if __name__ == "__main__":
    # Auto-reload while iterating: DEMO_RELOAD=1 python -m app.app
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("DEMO_RELOAD") == "1")
