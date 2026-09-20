"""Pre-demo readiness check. Run this every rehearsal and on the morning of the event.

    python -m tools.preflight           # check and report, changes nothing
    python -m tools.preflight --fix     # also start PostgreSQL and correct the firewall

Two things go wrong repeatedly and both are caught here:

  1. The public IP changes. It changed on three consecutive sessions during the
     build. An empty firewall list is allow-all for Cosmos but deny-all for
     PostgreSQL, so a stale list looks like a permissions bug and is not one.
  2. PostgreSQL gets stopped to park the cost, and a stopped server also breaks
     `terraform plan` on refresh.

Everything else is verification: the data is still loaded, the models still
answer, and the demo's two tuned data properties still hold.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from app import config

# Derived from .env rather than written down, so this file carries no identifiers
# belonging to any one subscription.
SUBSCRIPTION = config.SUBSCRIPTION_ID
PG_SERVER = config.POSTGRES_HOST.split(".", 1)[0]
COSMOS_ACCOUNT = config.COSMOS_ENDPOINT.split("//", 1)[-1].split(".", 1)[0]

STACK = Path(
    os.getenv("DEMO_TF_STACK", config.ROOT / "infra" / "terraform")
)
TFVARS = Path(os.getenv("DEMO_TF_VARS", STACK / "terraform.tfvars"))

EXPECTED_TICKETS = 1000
RARE_CODE = "ERR-5012"
RARE_CODE_COUNT = 13
ABSENT_WORD = "shaking"

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> bool:
    results.append((status, name, detail))
    mark = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn "}[status]
    print(f"[{mark}] {name}" + (f"  {detail}" if detail else ""), flush=True)
    return status == PASS


def az(*args: str, check: bool = True) -> str:
    out = subprocess.run(["az", *args], capture_output=True, text=True)
    if check and out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return out.stdout.strip()


def public_ip() -> str:
    with urllib.request.urlopen("https://api.ipify.org", timeout=15) as r:
        return r.read().decode().strip()


# --------------------------------------------------------------------- checks


def check_login() -> bool:
    try:
        account = json.loads(az("account", "show", "-o", "json"))
    except Exception:
        return record(FAIL, "Azure CLI signed in", "run: az login")
    if SUBSCRIPTION and account["id"] != SUBSCRIPTION:
        return record(FAIL, "Azure subscription",
                      f"on {account['name']}, expected the one in SUBSCRIPTION_ID")
    return record(PASS, "Azure CLI signed in", f"{account['user']['name']}")


def firewall_allows(ip: str) -> tuple[bool, bool]:
    """Rules may be CIDRs or single addresses, so test containment, not equality."""
    address = ipaddress.ip_address(ip)

    cosmos_rules = az("cosmosdb", "show", "-g", config.RESOURCE_GROUP, "-n", COSMOS_ACCOUNT,
                      "--query", "ipRules[].ipAddressOrRange", "-o", "tsv").split()
    # An empty Cosmos filter means allow-all. "0.0.0.0" is its marker for
    # "allow Azure datacentres" and never matches a laptop.
    real = [r for r in cosmos_rules if r != "0.0.0.0"]
    in_cosmos = not real or any(address in ipaddress.ip_network(r, strict=False) for r in real)

    pg_rows = az("postgres", "flexible-server", "firewall-rule", "list", "-g", config.RESOURCE_GROUP,
                 "-n", PG_SERVER, "--query", "[].[startIpAddress,endIpAddress]", "-o", "tsv").splitlines()
    in_pg = False
    for row in pg_rows:
        parts = row.split()
        if len(parts) == 2 and ipaddress.ip_address(parts[0]) <= address <= ipaddress.ip_address(parts[1]):
            in_pg = True
    return in_cosmos, in_pg


def terraform_error(out: subprocess.CompletedProcess) -> str:
    """Terraform frames errors in box drawing. Pull out the actual message."""
    text = out.stderr or out.stdout
    messages = re.findall(r"Error:\s*(.+)", text)
    if messages:
        return "; ".join(dict.fromkeys(m.strip() for m in messages))[:300]
    return text.strip()[-300:] or "terraform failed with no message"


def check_firewall(fix: bool) -> bool:
    ip = public_ip()
    in_cosmos, in_pg = firewall_allows(ip)
    if in_cosmos and in_pg:
        return record(PASS, "Firewall allows this machine", ip)

    missing = ", ".join(n for n, ok in (("Cosmos", in_cosmos), ("PostgreSQL", in_pg)) if not ok)
    if not fix:
        return record(FAIL, "Firewall allows this machine",
                      f"{ip} missing from {missing}. Re-run with --fix, or edit "
                      f"allowed_ip_rules in {TFVARS.name} and apply")

    if not TFVARS.exists():
        return record(FAIL, "Firewall allows this machine",
                      f"{ip} missing from {missing}, and {TFVARS} not found. Set DEMO_TF_STACK")

    print(f"         adding {ip} to allowed_ip_rules and applying, Cosmos takes about 8 minutes")
    text = TFVARS.read_text()
    block = re.search(r"allowed_ip_rules\s*=\s*\[(.*?)\]", text, re.S)
    if not block:
        return record(FAIL, "Firewall allows this machine", "could not find allowed_ip_rules in the tfvars")

    # Append rather than replace, so a venue address does not silently remove
    # office access and strand the next rehearsal.
    existing = [line.strip() for line in block.group(1).splitlines() if line.strip()]
    entry = f'"{ip}/32", # added by preflight {time.strftime("%d %b %H:%M")}'
    TFVARS.write_text(text.replace(
        block.group(0),
        "allowed_ip_rules = [\n  " + "\n  ".join(existing + [entry]) + "\n]"))

    started = time.time()
    out = subprocess.run(
        ["terraform", "apply", f"-var-file={TFVARS}", "-input=false", "-auto-approve"],
        cwd=STACK, capture_output=True, text=True,
    )
    if out.returncode != 0:
        return record(FAIL, "Firewall allows this machine", terraform_error(out))
    in_cosmos, in_pg = firewall_allows(ip)
    if in_cosmos and in_pg:
        return record(PASS, "Firewall allows this machine", f"{ip}, applied in {time.time() - started:.0f}s")
    return record(FAIL, "Firewall allows this machine", "apply finished but the rules still do not match")


def check_postgres_running(fix: bool) -> bool:
    state = az("postgres", "flexible-server", "show", "-g", config.RESOURCE_GROUP,
               "-n", PG_SERVER, "--query", "state", "-o", "tsv")
    if state == "Ready":
        return record(PASS, "PostgreSQL server running")
    if not fix:
        return record(FAIL, "PostgreSQL server running",
                      f"state is {state}. Re-run with --fix, or: az postgres flexible-server start "
                      f"-g {config.RESOURCE_GROUP} -n {PG_SERVER}")
    if state == "Stopped":
        print("         starting the server, this takes a few minutes")
        az("postgres", "flexible-server", "start", "-g", config.RESOURCE_GROUP, "-n", PG_SERVER)
    for _ in range(40):
        state = az("postgres", "flexible-server", "show", "-g", config.RESOURCE_GROUP,
                   "-n", PG_SERVER, "--query", "state", "-o", "tsv")
        if state == "Ready":
            return record(PASS, "PostgreSQL server running", "started")
        time.sleep(15)
    return record(FAIL, "PostgreSQL server running", f"still {state} after 10 minutes")


def check_cosmos_data() -> bool:
    from app import cosmos_store
    try:
        total = cosmos_store._run("SELECT VALUE COUNT(1) FROM c", [])[0]
    except Exception as exc:
        return record(FAIL, "Cosmos DB has the tickets", f"{type(exc).__name__}: {str(exc)[:120]}")
    if total != EXPECTED_TICKETS:
        return record(FAIL, "Cosmos DB has the tickets",
                      f"{total} documents, expected {EXPECTED_TICKETS}. Run: python -m tools.load_cosmos --recreate")
    return record(PASS, "Cosmos DB has the tickets", f"{total} documents")


def check_postgres_data() -> bool:
    from app import postgres_store
    try:
        total = postgres_store.stats()["total"]
    except Exception as exc:
        return record(FAIL, "PostgreSQL has the tickets", f"{type(exc).__name__}: {str(exc)[:120]}")
    if total != EXPECTED_TICKETS:
        return record(FAIL, "PostgreSQL has the tickets",
                      f"{total} rows, expected {EXPECTED_TICKETS}. Run: python -m tools.load_postgres --recreate")
    return record(PASS, "PostgreSQL has the tickets", f"{total} rows")


def check_demo_invariants() -> bool:
    """The two tuned properties the keyword-versus-vector story depends on."""
    from app import cosmos_store
    try:
        rare = cosmos_store.keyword_count(RARE_CODE)
        absent = cosmos_store.keyword_count(ABSENT_WORD)
    except Exception as exc:
        return record(FAIL, "Demo data still makes the point", str(exc)[:120])
    if rare != RARE_CODE_COUNT or absent != 0:
        return record(FAIL, "Demo data still makes the point",
                      f"{RARE_CODE} in {rare} tickets (want {RARE_CODE_COUNT}), "
                      f"'{ABSENT_WORD}' in {absent} (want 0)")
    return record(PASS, "Demo data still makes the point",
                  f"{RARE_CODE} in {rare}, '{ABSENT_WORD}' in 0")


def check_throughput() -> bool:
    """Throughput is set outside Terraform, so it is the thing most likely to drift."""
    from app import cosmos_store
    raw = az("cosmosdb", "sql", "container", "throughput", "show",
             "-g", config.RESOURCE_GROUP, "-a", COSMOS_ACCOUNT,
             "-d", config.COSMOS_DATABASE, "-n", config.COSMOS_CONTAINER, "-o", "json")
    resource = json.loads(raw)["resource"]
    settings = resource.get("autoscaleSettings") or {}
    ceiling = settings.get("maxThroughput")
    if not ceiling:
        return record(WARN, "Cosmos throughput", f"manual {resource.get('throughput')} RU/s, not autoscale")
    floor = int(resource.get("minimumThroughput") or 0)
    expected = cosmos_store.AUTOSCALE_MAX_RU
    # Anything above the expected ceiling is billing a larger floor for no gain.
    if ceiling > expected:
        return record(WARN, "Cosmos throughput",
                      f"autoscale to {ceiling} RU/s, expected {expected}. "
                      f"Billing a floor of {floor} RU/s for headroom nothing uses")
    return record(PASS, "Cosmos throughput", f"autoscale to {ceiling} RU/s, floor {floor}")


def check_graph() -> bool:
    from app import graph_store
    try:
        counts = graph_store.stats()
    except Exception as exc:
        return record(FAIL, "Graph is built", f"{type(exc).__name__}: {str(exc)[:110]}. "
                                              f"Run: python -m tools.load_graph --recreate")
    if counts.get("ticket") != EXPECTED_TICKETS:
        return record(FAIL, "Graph is built",
                      f"{counts.get('ticket')} ticket nodes, expected {EXPECTED_TICKETS}. "
                      f"Run: python -m tools.load_graph --recreate")
    return record(PASS, "Graph is built",
                  f"{counts['ticket']} tickets, {counts['asset']} assets, {counts['edges']} edges")


def check_graph_reveals() -> bool:
    """The graph panel only earns its place if the semantic edge reaches assets
    that no fault-code filter could. Anything less is a GROUP BY in a costume."""
    from app import graph_store
    try:
        result = graph_store.expand("the terminal freezes in the middle of a transaction")
    except Exception as exc:
        return record(FAIL, "Graph reaches assets SQL cannot", str(exc)[:120])
    meaning_only = result.get("meaning_only", [])
    if not meaning_only:
        return record(WARN, "Graph reaches assets SQL cannot",
                      "no asset reached by the SIMILAR_TO edge alone, the panel loses its point. "
                      "Run: python -m tools.load_graph --recreate")
    domains = {a["domain"] for a in meaning_only}
    names = ", ".join(a["asset"] for a in meaning_only)
    return record(PASS, "Graph reaches assets SQL cannot",
                  f"{len(meaning_only)} across {len(domains)} domains: {names}")


def check_search() -> bool:
    """The single most important query in the talk."""
    from app import cosmos_store
    try:
        rows, _ = cosmos_store.vector_search("equipment shaking when running hard")
    except Exception as exc:
        return record(FAIL, "Vector search returns the pump tickets", str(exc)[:120])
    codes = [r["error_code"] for r in rows]
    if codes.count(RARE_CODE) < 3:
        return record(FAIL, "Vector search returns the pump tickets", f"got {codes}")
    return record(PASS, "Vector search returns the pump tickets", f"{codes.count(RARE_CODE)} of {len(codes)} are {RARE_CODE}")


def check_models() -> bool:
    from app import foundry
    ok = True
    try:
        vector = foundry.embed_one("preflight", config.COSMOS_DIMS)
        ok &= record(PASS, "Foundry embeddings answer", f"{len(vector)} dims")
    except Exception as exc:
        ok &= record(FAIL, "Foundry embeddings answer", str(exc)[:140])
    try:
        from azure.ai.inference.models import SystemMessage, UserMessage
        from app import grounding
        reply = grounding._ask([SystemMessage("Reply with the single word: ready."), UserMessage("Ready?")])
        ok &= record(PASS, "Foundry chat answers", f"{config.CHAT_MODEL}: {reply[:40]}")
    except Exception as exc:
        ok &= record(FAIL, "Foundry chat answers", str(exc)[:140])
    return ok


def check_postgres_managed_identity() -> bool:
    """The claim that PostgreSQL calls the model itself. Prove it, do not assume it."""
    from app import postgres_store
    try:
        conn = postgres_store._session()
        with conn.cursor() as cur:
            cur.execute("SELECT azure_ai.get_setting('azure_openai.auth_type')")
            auth = cur.fetchone()[0]
            cur.execute(
                "SELECT array_length(azure_openai.create_embeddings(%s, 'preflight', dimensions => %s), 1)",
                (config.POSTGRES_MODEL, config.POSTGRES_DIMS),
            )
            dims = cur.fetchone()[0]
        conn.commit()
    except Exception as exc:
        return record(FAIL, "PostgreSQL reaches Foundry itself", str(exc)[:140])
    if auth != "managed-identity" or dims != config.POSTGRES_DIMS:
        return record(FAIL, "PostgreSQL reaches Foundry itself", f"auth={auth}, dims={dims}")
    return record(PASS, "PostgreSQL reaches Foundry itself", f"{auth}, {dims} dims")


def check_postgres_reasoning() -> bool:
    """azure_ai.generate hardcodes temperature 0.2, which gpt-5.5 rejects outright."""
    from app import postgres_store
    try:
        conn = postgres_store._session()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT azure_ai.generate('Reply with the single word: ready', model => %s)",
                (config.PG_CHAT_MODEL,),
            )
            reply = cur.fetchone()[0]
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return record(FAIL, "PostgreSQL generates answers", str(exc)[:140])
    return record(PASS, "PostgreSQL generates answers", f"{config.PG_CHAT_MODEL}: {reply[:40]}")


def check_app_starts() -> bool:
    try:
        from app.app import app as flask_app
        with flask_app.test_client() as client:
            for path in ("/", "/cosmos", "/postgres", "/graph"):
                page = client.get(path)
                if page.status_code != 200:
                    return record(FAIL, "All four pages render", f"{path} returned {page.status_code}")
                if b"banner error" in page.data:
                    return record(FAIL, "All four pages render", f"{path} shows an error banner")
    except Exception as exc:
        return record(FAIL, "All four pages render", f"{type(exc).__name__}: {str(exc)[:120]}")
    return record(PASS, "All four pages render")


def check_notebook_fallback() -> bool:
    notebook = config.ROOT / "src" / "ai-db-demos.ipynb"
    if not notebook.exists():
        return record(FAIL, "Notebook fallback has saved output", "file is missing")
    cells = json.loads(notebook.read_text())["cells"]
    code = [c for c in cells if c["cell_type"] == "code"]
    with_output = [c for c in code if c.get("outputs")]
    if len(with_output) < len(code) - 1:
        return record(WARN, "Notebook fallback has saved output",
                      f"only {len(with_output)} of {len(code)} cells have output, re-run it")
    return record(PASS, "Notebook fallback has saved output", f"{len(with_output)} of {len(code)} cells")


# ----------------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true",
                        help="start PostgreSQL and correct the firewall rather than only reporting")
    args = parser.parse_args()

    print(f"\nPreflight for the Oslo demo, {time.strftime('%a %d %b %Y %H:%M')}")
    print("=" * 72)

    print("\nAccess")
    if not check_login():
        print("\nStopping: nothing else can be checked without a signed-in CLI.")
        sys.exit(1)
    # Postgres first: Terraform cannot modify a firewall rule on a server that is
    # still starting, and it fails the whole apply when it tries.
    check_postgres_running(args.fix)
    check_firewall(args.fix)

    print("\nData")
    check_cosmos_data()
    check_postgres_data()
    check_graph()
    check_demo_invariants()
    check_throughput()

    print("\nModels")
    check_models()
    check_postgres_managed_identity()
    check_postgres_reasoning()

    print("\nThe demo itself")
    check_search()
    check_graph_reveals()
    check_app_starts()
    check_notebook_fallback()

    failed = [r for r in results if r[0] == FAIL]
    warned = [r for r in results if r[0] == WARN]
    print("\n" + "=" * 72)
    if failed:
        print(f"{len(failed)} of {len(results)} checks FAILED\n")
        for _, name, detail in failed:
            print(f"  {name}\n      {detail}")
        print("\nFix these before going on stage.")
        sys.exit(1)
    print(f"All {len(results)} checks passed" + (f", {len(warned)} warning" if warned else ""))
    print("\nStart the demo:  python -m app.app      then http://127.0.0.1:5000")
    print("Park it after :  az postgres flexible-server stop -g "
          f"{config.RESOURCE_GROUP} -n {PG_SERVER}")


if __name__ == "__main__":
    main()
