"""Exercise every endpoint with every dropdown option, then every button.

    python -m tools.smoke            API sweep only
    python -m tools.smoke --browser  also click through the pages

Preflight proves the environment is sound. This proves the demo is sound: each
answer is checked for the fields its renderer actually reads, because a missing
key shows up on stage as a blank panel rather than as an error.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

from app import queries

BASE = "http://127.0.0.1:5000"
PASS, FAIL = "[  ok  ]", "[ FAIL ]"

failures: list[str] = []


def post(path: str, body: dict) -> tuple[dict, int]:
    data = json.dumps(body).encode()
    request = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.load(response)
    return payload, int((time.time() - started) * 1000)


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{PASS if ok else FAIL} {label:<58} {detail}")
    if not ok:
        failures.append(label)
    return ok


def rows_endpoint(path: str, panel: str, require: list[str]) -> None:
    """Endpoints whose renderer walks data.rows and reads data.sql."""
    for option in queries.CATALOGUE[panel]:
        value = option["value"]
        try:
            data, ms = post(path, {"q": value})
        except Exception as exc:
            check(f"{path}  {value[:34]}", False, str(exc)[:70])
            continue
        if data.get("error"):
            check(f"{path}  {value[:34]}", False, data["error"][:70])
            continue
        missing = [k for k in require if k not in data]
        # Zero rows is a legitimate answer for 'shaking'. A missing key is not.
        detail = f"{len(data.get('rows', []))} rows, {ms} ms"
        check(f"{path}  {value[:34]}", not missing, detail if not missing else f"missing {missing}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true", help="also click every button")
    args = parser.parse_args()

    print("\nPages")
    for path in ("/", "/cosmos", "/postgres", "/graph"):
        try:
            with urllib.request.urlopen(BASE + path, timeout=60) as response:
                body = response.read().decode()
            check(f"GET {path}", response.status == 200 and "<h2" in body, f"{len(body)} bytes")
        except Exception as exc:
            check(f"GET {path}", False, str(exc)[:70])

    print("\nCosmos DB")
    rows_endpoint("/api/keyword", "keyword", ["rows", "sql", "ms"])
    rows_endpoint("/api/vector", "vector", ["rows", "sql", "ms"])
    rows_endpoint("/api/filtered", "filtered", ["rows", "sql", "ms"])
    rows_endpoint("/api/hybrid", "hybrid", ["rows", "sql", "ms"])

    print("\nPostgreSQL")
    rows_endpoint("/api/pg/search", "postgres", ["rows", "sql", "ms"])
    rows_endpoint("/api/pg/aggregate", "postgres", ["rows", "sql", "ms"])
    rows_endpoint("/api/pg/explain", "postgres", ["rows", "sql", "ms"])
    rows_endpoint("/api/pg/hybrid", "postgres", ["rows", "sql", "ms"])

    print("\nThe claims that have to hold")
    invariants()

    print("\nReasoning in SQL")
    for option in queries.CATALOGUE["postgres"]:
        value = option["value"]
        try:
            data, ms = post("/api/pg/answer", {"q": value})
        except Exception as exc:
            check(f"pg/answer  {value[:38]}", False, str(exc)[:70])
            continue
        answer = data.get("answer", "")
        cites = data.get("citations", [])
        fake = [c["ticket_id"] for c in cites if not c["exists"]]
        ok = bool(answer) and not data.get("error") and not fake and bool(cites)
        detail = f"{len(answer)} chars, {len(cites)} cites, {ms} ms"
        check(f"pg/answer  {value[:38]}", ok, detail if ok else f"fake={fake} err={data.get('error','')[:40]}")

    print("\nGrounding, both sides")
    for option in queries.CATALOGUE["grounded"]:
        value = option["value"]
        try:
            data, ms = post("/api/grounded", {"q": value})
        except Exception as exc:
            check(f"grounded  {value[:39]}", False, str(exc)[:70])
            continue
        try:
            k, s = data["keyword"], data["semantic"]
        except KeyError:
            check(f"grounded  {value[:39]}", False, f"missing sides: {list(data)}")
            continue
        fake = [c["ticket_id"] for c in s["citations"] if not c["exists"]]
        # The whole panel rests on keyword finding nothing and vectors finding
        # plenty. If that ever flips, the story stops working.
        ok = (
            len(k["rows"]) == 0
            and len(s["rows"]) > 0
            and bool(s["citations"])
            and not fake
        )
        detail = f"keyword {len(k['rows'])} rows, vector {len(s['rows'])} rows, {len(s['citations'])} cites, {ms} ms"
        check(f"grounded  {value[:39]}", ok, detail if ok else f"{detail} fake={fake}")

    print("\nThe graph")
    for option in queries.CATALOGUE["graph"]:
        value = option["value"]
        try:
            data, ms = post("/api/graph", {"q": value})
        except Exception as exc:
            check(f"graph  {value[:41]}", False, str(exc)[:70])
            continue
        required = {"code", "seeds", "assets", "meaning_only", "layout", "cypher"}
        missing = required - set(data)
        meaning = data.get("meaning_only", [])
        layout_kinds = {n["kind"] for n in data.get("layout", {}).get("nodes", [])}
        # Every meaning-only asset must be drawn as one, or the diagram and the
        # table disagree in front of the room.
        drawn = len(meaning) == 0 or "meaning" in layout_kinds
        ok = not missing and drawn
        detail = f"{data.get('code')}, {len(data.get('assets', []))} assets, {len(meaning)} by meaning, {ms} ms"
        check(f"graph  {value[:41]}", ok, detail if ok else f"missing={missing} drawn={drawn}")

    if args.browser:
        print("\nEvery button, in a real browser")
        browser_pass()

    print("\n" + "=" * 78)
    if failures:
        print(f"{len(failures)} failed:")
        for name in failures:
            print(f"  {name}")
        raise SystemExit(1)
    print("Everything passed")


def invariants() -> None:
    """The three numbers the narrative depends on."""
    data, _ = post("/api/keyword", {"q": "ERR-5012"})
    check("keyword ERR-5012 still finds 13", data.get("total_matches") == 13,
          f"{data.get('total_matches')}")
    data, _ = post("/api/keyword", {"q": "shaking"})
    check("keyword 'shaking' still finds 0", data.get("total_matches") == 0,
          f"{data.get('total_matches')}")
    data, _ = post("/api/vector", {"q": "equipment shaking when running hard"})
    codes = [r["error_code"] for r in data.get("rows", [])]
    check("vector 'shaking' still finds the pumps", codes.count("ERR-5012") >= 3,
          f"{codes.count('ERR-5012')} of {len(codes)} are ERR-5012")


def browser_pass() -> None:
    from playwright.sync_api import sync_playwright

    pages = {
        "/": ["embed"],
        "/cosmos": ["keyword", "vector", "filtered", "hybrid", "grounded"],
        "/postgres": ["pg/search", "pg/explain", "pg/answer", "pg/aggregate", "pg/hybrid"],
        "/graph": ["graph"],
    }
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        console: list[str] = []
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        for path, endpoints in pages.items():
            page.goto(BASE + path, wait_until="networkidle")
            for endpoint in endpoints:
                button = page.locator(f"button[data-run='{endpoint}']").first
                target = button.get_attribute("data-target") or endpoint
                button.click()
                out = page.locator(f"#out-{target}")
                try:
                    out.locator(":scope > *").first.wait_for(timeout=180_000)
                    page.wait_for_function(
                        "id => !document.getElementById(id).querySelector('.working')",
                        arg=f"out-{target}",
                        timeout=180_000,
                    )
                except Exception as exc:
                    check(f"click {endpoint:<14} on {path}", False, str(exc)[:60])
                    continue
                failed = out.locator(".failed").count()
                text = out.inner_text().strip()
                check(f"click {endpoint:<14} on {path}", failed == 0 and len(text) > 40,
                      f"{len(text)} chars rendered" if not failed else out.inner_text()[:70])
        browser.close()
        check("no JavaScript console errors", not console, "; ".join(console)[:70])


if __name__ == "__main__":
    main()
