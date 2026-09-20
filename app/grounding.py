"""Panel 5: the same model and prompt, fed by two different retrievals.

Comparing a grounded model against a model with no data at all proves nothing
anybody disputes. The honest question is not whether retrieval helps, it is
whether *your* retrieval is good enough, so both sides here are grounded and
the only variable is which search found the tickets.

Pasting the question into the full-text index returns nothing, so the left-hand
model truthfully reports that this has never happened before. It is wrong, it
is not a hallucination, and it is the answer an engineer would act on.

Cited ticket IDs are checked against the database afterwards. An ID that does
not exist is marked, which turns an abstract warning about hallucination into
something the room can see.
"""

from __future__ import annotations

import concurrent.futures
import re

from azure.ai.inference.models import SystemMessage, UserMessage

from . import config, cosmos_store, foundry

TICKET_ID = re.compile(r"INC-\d{4}-\d{4,5}")

SYSTEM = (
    "You are an operations support assistant for an industrial services company. "
    "Answer the engineer's question in at most 120 words, using only the tickets "
    "provided below. Cite the ticket IDs you relied on, in the form INC-2026-01234. "
    "If no tickets are provided, say plainly that we have no record of this "
    "happening before, and stop."
)


def _ask(messages: list) -> str:
    response = foundry.chat_client().complete(
        messages=messages,
        model=config.CHAT_MODEL,
        # gpt-5.5 rejects max_tokens and wants max_completion_tokens, which this
        # SDK version only passes through as a model extra.
        model_extras={"max_completion_tokens": 600},
    )
    return response.choices[0].message.content.strip()


def _format_context(rows: list[dict]) -> str:
    if not rows:
        return "(the search returned no tickets)"
    lines = []
    for row in rows:
        lines.append(
            f"{row['ticket_id']} | {row['domain']} | {row['asset']} | {row['error_code']} | "
            f"{row['severity']} | resolved in {row.get('resolved_hours')} h\n"
            f"  title: {row['title']}\n"
            f"  reported: {row['description']}\n"
            f"  resolution: {row.get('resolution') or 'still open'}"
        )
    return "\n".join(lines)


def verify_citations(answer: str) -> list[dict]:
    """Every cited ID, checked for existence. This is the part that lands."""
    checked = []
    for ticket_id in dict.fromkeys(TICKET_ID.findall(answer)):
        rows = list(
            cosmos_store.container().query_items(
                query="SELECT VALUE c.ticket_id FROM c WHERE c.ticket_id = @id",
                parameters=[{"name": "@id", "value": ticket_id}],
                enable_cross_partition_query=True,
            )
        )
        checked.append({"ticket_id": ticket_id, "exists": bool(rows)})
    return checked


def _prompt(question: str, rows: list[dict]) -> list:
    return [
        SystemMessage(SYSTEM),
        UserMessage(
            f"Tickets from our system:\n\n{_format_context(rows)}\n\nQuestion: {question}"
        ),
    ]


def compare(question: str, top_k: int = 8) -> dict:
    # The same question string goes to both engines. Anything else would be the
    # demo choosing the winner.
    keyword_rows, keyword_sql = cosmos_store.keyword_search(question, top_k=top_k)

    # Resolved tickets only: every question here asks what fixed it, and an open
    # ticket has nothing to contribute to that.
    vector_rows, vector_sql = cosmos_store.filtered_vector_search(
        question, resolved_only=True, top_k=top_k
    )

    # Both calls are independent, and on stage twelve seconds of silence is a
    # long time. Run them together.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(_ask, _prompt(question, keyword_rows))
        right = pool.submit(_ask, _prompt(question, vector_rows))
        keyword_answer, vector_answer = left.result(), right.result()

    return {
        "question": question,
        "keyword": {
            "answer": keyword_answer,
            "citations": verify_citations(keyword_answer),
            "rows": keyword_rows,
            "sql": keyword_sql,
        },
        "semantic": {
            "answer": vector_answer,
            "citations": verify_citations(vector_answer),
            "rows": vector_rows,
            "sql": vector_sql,
        },
        "model": config.CHAT_MODEL,
    }
