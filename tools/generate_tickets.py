"""Generate the synthetic operations ticket dataset used by the demo.

Deterministic: same seed, same file, so the committed CSV and the notebook
outputs never drift apart.

Structure matters here. A ticket is generated from one *scenario*, and its
title, description, resolution and error code all come from that same scenario.
Sampling those fields independently produces rows that look fine in aggregate
and obviously wrong when someone reads one off a projector.

Scenario weights control how often each fault occurs, which is what makes the
keyword demo work: common faults fill the table, and a deliberately rare fault
returns a handful of rows instead of a quarter of the dataset.

Each scenario's `descriptions` are the same problem in different words, sharing
as little vocabulary as possible. That gap is what vector search closes and
keyword search cannot.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 20260922
TICKET_COUNT = 1000
OUT = Path(__file__).resolve().parent.parent / "data" / "tickets.csv"

START = datetime(2026, 1, 6, 6, 0)

TEAMS = {
    "Maritime": ["Rotating Equipment", "Bridge Systems", "Hull & Deck"],
    "Energy": ["Grid Operations", "Substation Field", "SCADA"],
    "Payments": ["Payments Platform", "Fraud Engineering", "Core Banking"],
    "Retail": ["Store Systems", "Logistics", "E-commerce"],
}

ASSETS = {
    "Maritime": ["MV Nordlys", "MV Bergen Star", "MV Havbris", "MV Kvitøy", "MV Storfjord"],
    "Energy": ["Substation Kollsnes", "Substation Fana", "Substation Ålgård", "Substation Rong"],
    "Payments": ["Gateway North", "Gateway West", "Gateway Core", "Scoring Cluster A"],
    "Retail": ["Store 014 Oslo", "Store 031 Bergen", "Store 022 Trondheim", "DC Vestby", "DC Larvik"],
}

# weight: relative frequency. Low weight means a rare fault, which is what makes
# a search for its code return a small, meaningful set.
#
# Each scenario carries eight descriptions rather than three. With only a handful
# the same sentence appeared three or four times in a five row result, which on a
# projector reads as a broken demo rather than as a fleet reporting the same
# fault. They are also written to share as little vocabulary with each other as
# possible, since that gap is the thing vector search has to cross.
SCENARIOS = [
    # -- Maritime ----------------------------------------------------------
    {
        "domain": "Maritime",
        "component": "Bearing assembly",
        "error_code": "ERR-5012",
        "weight": 1,  # rare on purpose: this is the keyword-search example
        "severity": [("Critical", 2), ("High", 5)],
        "hours": (6.0, 20.0),
        "titles": [
            "Vibration alarm on main pump during ramp-up",
            "Pump running rough above 80% load",
            "Main pump noisy at high output",
        ],
        "descriptions": [
            "Engineer reports the unit shudders badly once load goes past roughly 80 percent. Settles down when throttled back.",
            "Crew noticed the whole skid moving more than normal at high output, with noise rising as speed increases.",
            "Trembling felt through the deck plate near the pump when running hard. Nothing at low load.",
            "Operator describes a rhythmic knocking that worsens the harder the unit works.",
            "Noticeable judder from the housing above three quarters output, easing off as soon as demand drops.",
            "Something is clearly out of balance. The harder it runs the worse the racket gets.",
            "Duty watch logged heavy oscillation on the unit at full output, quiet again once throttled.",
            "The mounting feels alive under your hand when the machine is worked hard.",
        ],
        "resolutions": [
            "Bearing clearance out of tolerance. Replaced bearing set and re-aligned coupling, vibration back within limits.",
            "Soft foot on the mounting. Shimmed and re-torqued base bolts, retested at full load with no recurrence.",
            "Worn bearing races found on strip down. Renewed both bearings and rechecked alignment cold and hot.",
        ],
    },
    {
        "domain": "Maritime",
        "component": "Fuel system",
        "error_code": "ERR-5140",
        "weight": 9,
        "severity": [("High", 3), ("Medium", 6), ("Low", 1)],
        "hours": (2.0, 10.0),
        "titles": [
            "Fuel pressure fluctuating on auxiliary engine",
            "Auxiliary engine losing power intermittently",
            "Uneven running on auxiliary engine",
        ],
        "descriptions": [
            "Pressure reading swings up and down rather than holding steady, and the engine surges slightly with it.",
            "Engine drops revs briefly every few minutes then recovers on its own.",
            "Output is uneven under steady demand, with no alarm raised.",
            "Gauge will not settle. It wanders either side of where it should sit.",
            "Brief hesitation every so often, as though it is starving for a moment and then catching again.",
            "Watch reports the machine hunting at constant load, never quite holding a figure.",
            "Power dips away and returns without anyone touching the controls.",
            "Reading is restless. It never sits still long enough to take a proper number off it.",
        ],
        "resolutions": [
            "Fuel filter partially blocked. Replaced the element and bled the system.",
            "Air ingress at a loose union on the suction side. Tightened and pressure tested.",
            "Lift pump diaphragm perished. Renewed the pump and confirmed steady supply pressure.",
        ],
    },
    {
        "domain": "Maritime",
        "component": "Navigation display",
        "error_code": "ERR-2203",
        "weight": 7,
        "severity": [("High", 3), ("Medium", 6), ("Low", 2)],
        "hours": (1.0, 8.0),
        "titles": [
            "Chart display freezing on bridge console",
            "Bridge display unresponsive during watch",
            "Console blanking intermittently",
        ],
        "descriptions": [
            "Screen locks up for around thirty seconds then returns on its own, several times per watch.",
            "Display goes dark without warning and comes back after a minute, nothing in the alarm log.",
            "Console stops responding to touch and only recovers after a power cycle.",
            "Picture freezes mid update. Everything else on the bridge carries on as normal.",
            "Goes black for a moment, then paints itself back in as if nothing happened.",
            "Watchkeeper cannot interact with it for short spells, then it wakes up again.",
            "Image stalls and the vessel symbol stops moving, though position is clearly still changing.",
            "Unit drops out briefly two or three times a watch, always without an alarm.",
        ],
        "resolutions": [
            "Loose display cable at the bulkhead connector. Reseated and secured, no further dropouts.",
            "Firmware defect in the chart renderer. Applied vendor patch 4.2.1.",
            "Failing power supply in the console. Replaced the unit and monitored for a full watch.",
        ],
    },
    # -- Energy ------------------------------------------------------------
    {
        "domain": "Energy",
        "component": "Transformer cooling",
        "error_code": "ERR-7744",
        "weight": 8,
        "severity": [("Critical", 3), ("High", 6), ("Medium", 2)],
        "hours": (4.0, 26.0),
        "titles": [
            "Transformer temperature trending high",
            "Overtemperature warning during evening peak",
            "Unit running warmer than its neighbours",
        ],
        "descriptions": [
            "Readings climb steadily through the afternoon peak and no longer settle overnight the way they used to.",
            "Unit runs hotter than the others on the same bus under identical load.",
            "Temperature creeping up over several days with no change in demand to explain it.",
            "Thermal margin has been shrinking week on week and nobody can point at a cause.",
            "It is noticeably warmer to stand next to than the one beside it, carrying the same current.",
            "Control room sees the figure drifting upward and not recovering during the quiet hours.",
            "Gradual rise on the trend, small each day, obvious across a month.",
            "Sits several degrees above where it has historically run, with load unchanged.",
        ],
        "resolutions": [
            "Two cooling fans had failed. Replaced both, temperature returned to its normal profile within the hour.",
            "Radiator fins heavily fouled. Cleaned and flushed to restore rated cooling capacity.",
            "Blocked airflow from vegetation growth against the enclosure. Cleared and trimmed back.",
        ],
    },
    {
        "domain": "Energy",
        "component": "SCADA link",
        "error_code": "ERR-3310",
        "weight": 9,
        "severity": [("High", 4), ("Medium", 6), ("Low", 2)],
        "hours": (1.0, 12.0),
        "titles": [
            "Telemetry gap from remote site",
            "SCADA polling timeouts overnight",
            "Outstation dropping off the system",
        ],
        "descriptions": [
            "Control room had no readings from the site for about twenty minutes, then everything reappeared at once.",
            "Data stopped arriving during the night shift and backfilled automatically once the link recovered.",
            "Intermittent loss of contact with the outstation, several short gaps through the evening.",
            "The site went quiet. Nothing came in until it suddenly caught up in one burst.",
            "We lose sight of it for minutes at a time and then it is back as though nothing happened.",
            "Trend shows holes in the record overnight that filled themselves in by morning.",
            "Nothing reported in from that location for a stretch, with no alarm to say why.",
            "Values freeze at their last figure, then jump to current once contact returns.",
        ],
        "resolutions": [
            "Radio link degraded by weather. Repointed the antenna and improved the margin.",
            "Polling interval too aggressive after a config change. Reverted to the previous setting.",
            "Failing media converter at the site end. Swapped the unit and the gaps stopped.",
        ],
    },
    {
        "domain": "Energy",
        "component": "Protection relay",
        "error_code": "ERR-7120",
        "weight": 3,
        "severity": [("Critical", 4), ("High", 4)],
        "hours": (3.0, 18.0),
        "titles": [
            "Unexpected breaker trip on feeder",
            "Relay operated with no fault found",
            "Feeder lost supply without cause",
        ],
        "descriptions": [
            "Feeder tripped out with nothing obvious on the line, and supply was restored manually after inspection.",
            "Protection operated during a routine switching sequence, with no damage identified downstream.",
            "Breaker opened on its own. Walked the route and found nothing wrong.",
            "Supply dropped with no weather, no work in progress and nothing on the overhead.",
            "Came out for no reason anyone can establish, reclosed first time and has behaved since.",
            "Operated during normal conditions, and a full inspection turned up nothing at all.",
            "Went off with a clean line. Nothing burnt, nothing down, nothing touching it.",
            "Trip with no accompanying disturbance recorded anywhere on the network.",
        ],
        "resolutions": [
            "Relay setting group left on the commissioning profile. Restored operational settings.",
            "Current transformer wiring reversed on one phase after maintenance. Corrected and tested.",
            "Moisture ingress in the relay panel causing spurious operation. Dried, sealed and retested.",
        ],
    },
    # -- Payments ----------------------------------------------------------
    {
        "domain": "Payments",
        "component": "Card authorisation",
        "error_code": "ERR-4001",
        "weight": 9,
        "severity": [("Critical", 4), ("High", 6), ("Medium", 1)],
        "hours": (0.5, 6.0),
        "titles": [
            "Elevated decline rate on card payments",
            "Customers reporting failed checkout",
            "Authorisation success rate dropped",
        ],
        "descriptions": [
            "Success rate dropped from its usual level to around eighty percent over about ten minutes.",
            "Customers say payment spins and then fails, and a retry usually works on the second attempt.",
            "More transactions than normal are being turned away, with no pattern by card type or issuer.",
            "Approval numbers fell off a cliff and have not come back on their own.",
            "People are being refused at the final step even though their cards are perfectly good.",
            "Support is fielding complaints that the payment page hangs and then gives up.",
            "A fifth of attempts are bouncing back, where it is normally a rounding error.",
            "Volume looks normal but far fewer of them are completing than they should.",
        ],
        "resolutions": [
            "Upstream acquirer degraded. Failed over to the secondary route and rates recovered immediately.",
            "Connection pool exhausted after a traffic spike. Raised the pool size and added backpressure.",
            "Expired certificate on the acquirer link. Renewed and redeployed, success rate normalised.",
        ],
    },
    {
        "domain": "Payments",
        "component": "Fraud scoring",
        "error_code": "ERR-4102",
        "weight": 6,
        "severity": [("High", 4), ("Medium", 6), ("Low", 1)],
        "hours": (2.0, 18.0),
        "titles": [
            "Fraud model scoring slowly",
            "False positives spiking on new rule",
            "Review queue backing up",
        ],
        "descriptions": [
            "Scoring calls take several seconds where they normally return almost instantly.",
            "Far more legitimate transactions are being held for review than usual since yesterday.",
            "Overnight job still running well into the morning, leaving downstream reports delayed.",
            "The model is taking its time. What used to be instant now has a noticeable wait.",
            "Analysts are drowning in referrals that turn out to be perfectly ordinary purchases.",
            "Queue depth has been climbing all day and the team cannot work through it fast enough.",
            "Genuine customers are being stopped at a rate we have not seen before.",
            "Response times have crept up to the point where the checkout feels sluggish.",
        ],
        "resolutions": [
            "Feature store query missing an index after a schema change. Index rebuilt and latency recovered.",
            "Threshold misconfigured during deployment. Corrected and validated against the holdout set.",
            "Stale model artefact loaded on two nodes. Redeployed the correct version across the cluster.",
        ],
    },
    {
        "domain": "Payments",
        "component": "Settlement batch",
        "error_code": "ERR-4310",
        "weight": 4,
        "severity": [("High", 5), ("Medium", 4)],
        "hours": (3.0, 22.0),
        "titles": [
            "Settlement file rejected by clearing",
            "End of day batch did not complete",
            "Daily reconciliation out by a file",
        ],
        "descriptions": [
            "The file came back rejected with a format complaint, so settlement did not post for the day.",
            "Batch stalled partway through and had to be restarted from the last checkpoint.",
            "Clearing would not take the submission, so nothing landed where it should have.",
            "Overnight run stopped halfway and left the day only partly posted.",
            "Submission bounced. The totals at the end of it did not agree with the body.",
            "Job died in the middle and had to be picked up again from where it gave out.",
            "Nothing settled last night, and the counterparty has not received anything from us.",
            "The run failed silently and was only noticed when the morning figures did not balance.",
        ],
        "resolutions": [
            "Trailing record count mismatch caused by a duplicated entry. Deduplicated and resubmitted.",
            "Downstream schema change not applied in our mapping. Updated the mapping and reran.",
            "Disk exhausted on the batch host mid write. Cleared space, added an alert and reran cleanly.",
        ],
    },
    # -- Retail ------------------------------------------------------------
    {
        "domain": "Retail",
        "component": "Point of sale",
        "error_code": "ERR-6205",
        "weight": 9,
        "severity": [("High", 4), ("Medium", 6), ("Low", 2)],
        "hours": (1.0, 9.0),
        "titles": [
            "Till freezing during busy period",
            "Checkout terminal restarting unexpectedly",
            "Lane out of service at peak",
        ],
        "descriptions": [
            "Terminal locks solid mid transaction when the queue is long and staff have to restart it.",
            "Unit reboots by itself a few times a day, always around the busiest hours.",
            "Screen stops accepting input at the worst moment and the sale has to be started again.",
            "It gives up under pressure. Quiet mornings are fine, Saturday afternoon is not.",
            "Staff lose the lane completely and have to move the queue to the next one.",
            "Goes down on its own without anyone touching it, then comes back a minute later.",
            "Freezes solid with a customer standing there and the basket half scanned.",
            "Cuts out repeatedly once the shop fills up, never when it is quiet.",
        ],
        "resolutions": [
            "Faulty power supply under load. Replaced the unit with no repeat over the following week.",
            "Thermal shutdown from blocked vents behind the counter. Relocated and cleaned.",
            "Failing memory module. Swapped the board and soak tested through a full trading day.",
        ],
    },
    {
        "domain": "Retail",
        "component": "Inventory sync",
        "error_code": "ERR-6410",
        "weight": 8,
        "severity": [("High", 4), ("Medium", 5), ("Low", 2)],
        "hours": (2.0, 20.0),
        "titles": [
            "Stock levels out of step with warehouse",
            "Online availability showing items that are sold out",
            "Counts disagree between systems",
        ],
        "descriptions": [
            "The website is offering products the shelf does not actually have, and customers arrive to collect nothing.",
            "Counts in the system do not match what staff find when they physically check the shelf.",
            "The nightly transfer arrived hours late, so morning picking worked from stale numbers.",
            "We are selling things we do not hold, and the first anyone knows is at the collection point.",
            "Numbers on screen and numbers on the rack are two different stories.",
            "Figures are a day behind, so every decision this morning was made on yesterday's picture.",
            "Customers are ordering items that ran out before the order was even placed.",
            "What the system believes is in the building bears no relation to what is in the building.",
        ],
        "resolutions": [
            "Sync job failing silently on malformed records. Added validation and alerting, then reprocessed the backlog.",
            "Clock skew between systems caused updates to be discarded as out of order. Corrected NTP.",
            "Message queue backed up behind a poison message. Removed it and replayed the remainder.",
        ],
    },
    {
        "domain": "Retail",
        "component": "Receipt printer",
        "error_code": "ERR-6250",
        "weight": 5,
        "severity": [("Medium", 6), ("Low", 4)],
        "hours": (0.5, 5.0),
        "titles": [
            "Receipt printer not responding",
            "Printing stops partway through a sale",
            "No receipt at end of transaction",
        ],
        "descriptions": [
            "Printer stops halfway through and the sale has to be voided and rerun.",
            "Nothing comes out at all, though the terminal reports the sale completed.",
            "Paper feeds a few lines then gives up, leaving the customer with half a slip.",
            "Staff hand over a torn stub because the machine quit in the middle of it.",
            "The till says done and the customer gets nothing to take away.",
            "It produces the top of the receipt and then simply stops.",
            "Output dies mid print and the transaction has to be put through again.",
            "No paper comes through even though everything else about the sale worked.",
        ],
        "resolutions": [
            "Printer driver incompatible with the latest POS release. Rolled back the driver.",
            "Paper sensor dirty and reporting empty. Cleaned and recalibrated.",
            "Worn feed roller slipping under load. Replaced the roller assembly.",
        ],
    },
]

STATUSES = [("Resolved", 8), ("Closed", 3), ("In Progress", 1)]


def weighted(rng: random.Random, pairs: list[tuple[str, int]]) -> str:
    return rng.choices([v for v, _ in pairs], weights=[w for _, w in pairs], k=1)[0]


def build_rows(rng: random.Random, count: int) -> list[dict]:
    weights = [s["weight"] for s in SCENARIOS]
    rows: list[dict] = []

    for i in range(count):
        scenario = rng.choices(SCENARIOS, weights=weights, k=1)[0]
        domain = scenario["domain"]
        opened = START + timedelta(
            days=rng.randint(0, 250),
            hours=rng.randint(0, 23),
            minutes=rng.choice([0, 15, 30, 45]),
        )
        status = weighted(rng, STATUSES)
        low, high = scenario["hours"]
        still_open = status == "In Progress"

        rows.append(
            {
                "ticket_id": f"INC-2026-{4000 + i:05d}",
                "opened_at": opened.isoformat(timespec="minutes"),
                "domain": domain,
                "asset": rng.choice(ASSETS[domain]),
                "component": scenario["component"],
                "error_code": scenario["error_code"],
                "severity": weighted(rng, scenario["severity"]),
                "status": status,
                "team": rng.choice(TEAMS[domain]),
                "title": rng.choice(scenario["titles"]),
                # The reporter's own words, deliberately not reusing the title.
                "description": rng.choice(scenario["descriptions"]),
                "resolution": "" if still_open else rng.choice(scenario["resolutions"]),
                "resolved_hours": "" if still_open else f"{rng.uniform(low, high):.1f}",
            }
        )

    rng.shuffle(rows)
    return rows


def main() -> None:
    rng = random.Random(SEED)
    rows = build_rows(rng, TICKET_COUNT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    counts: dict[str, int] = {}
    domains: dict[str, int] = {}
    for row in rows:
        counts[row["error_code"]] = counts.get(row["error_code"], 0) + 1
        domains[row["domain"]] = domains.get(row["domain"], 0) + 1

    print(f"Wrote {len(rows)} tickets to {OUT}\n")
    print("by domain:")
    for domain, n in sorted(domains.items()):
        print(f"  {domain:10s} {n:4d}")
    print("\nerror code frequency (rarest first, these are the keyword examples):")
    for code, n in sorted(counts.items(), key=lambda kv: kv[1]):
        print(f"  {code}  {n:4d}")


if __name__ == "__main__":
    main()
