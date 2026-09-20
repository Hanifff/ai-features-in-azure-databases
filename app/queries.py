"""The queries offered in the UI.

Every query the demo runs is chosen from a dropdown. Nothing is typed on stage:
a typo in front of a room costs more than the flexibility is worth, and the
counts in these labels were measured against the committed dataset.

`note` is the point the query is there to make, shown under the result.
"""

from __future__ import annotations

KEYWORD_QUERIES = [
    {
        "value": "ERR-5012",
        "label": "ERR-5012",
        "note": "Exact codes are what keyword search is for. Nothing else finds these 13 rows as cleanly.",
    },
    {
        "value": "bearing",
        "label": "bearing",
        "note": "The word is in the text, so it is found. Keyword search is not weak, it is literal.",
    },
    {
        "value": "shaking",
        "label": "shaking",
        "note": "Zero results. The tickets describe shuddering, trembling and knocking. Same fault, different words, and literal matching cannot cross that gap.",
    },
    {
        "value": "vibration",
        "label": "vibration",
        "note": "Found, but only the reports that happened to use this word.",
    },
]

VECTOR_QUERIES = [
    {
        "value": "equipment shaking when running hard",
        "label": "equipment shaking when running hard",
        "note": "Not one word of this query appears in the tickets it returns. The match is on meaning, which is the whole argument for vectors.",
    },
    {
        "value": "customers cannot pay at the checkout",
        "label": "customers cannot pay at the checkout",
        "note": "Pulls together card declines and frozen tills: different systems, one customer experience.",
    },
    {
        "value": "we stopped receiving readings from a remote site",
        "label": "we stopped receiving readings from a remote site",
        "note": "Finds the telemetry gaps without using the word telemetry.",
    },
    {
        "value": "ERR-5012",
        "label": "ERR-5012",
        "note": "Weak, scattered results. A code carries no meaning to embed, so this is the failure case for vectors. Keyword search answered it perfectly.",
    },
]

FILTERED_QUERIES = [
    {
        "value": "equipment shaking when running hard",
        "label": "equipment shaking when running hard",
        "note": "Same meaning search, narrowed by metadata in the same request. One engine, one round trip.",
    },
    {
        "value": "customers cannot pay at the checkout",
        "label": "customers cannot pay at the checkout",
        "note": "Filtering is not post-processing. The filter runs inside the query, so the top results are the top results within scope.",
    },
    {
        "value": "something is overheating",
        "label": "something is overheating",
        "note": "A vague question, scoped to what matters. This is closer to how people actually ask.",
    },
]

HYBRID_QUERIES = [
    {
        "value": "ERR-5012 vibration at high load",
        "label": "ERR-5012 vibration at high load",
        "note": "A code and a symptom in one question. Keyword handles the code, vectors handle the symptom, and RRF fuses the two rankings inside the database.",
    },
    {
        "value": "printer stops mid sale ERR-6250",
        "label": "printer stops mid sale ERR-6250",
        "note": "Real questions are rarely purely one or the other, which is why fusing beats choosing.",
    },
    {
        "value": "pump knocking under load",
        "label": "pump knocking under load",
        "note": "No code here. Hybrid degrades gracefully to what vectors would have given you.",
    },
]

GROUNDED_QUESTIONS = [
    {
        "value": "A pump is vibrating badly above 80 percent load. Has this happened before, and what fixed it?",
        "label": "A pump is vibrating badly above 80 percent load. Has this happened before, and what fixed it?",
        "note": "Both sides are grounded. The left one was handed what the keyword index found, which was nothing, so it correctly reports that we have no record of this. It is wrong, and it is the answer the engineer acts on. The right one was handed the same question answered by meaning, and names the tickets and the fixes.",
    },
    {
        "value": "A transformer is running hotter than the others on the same bus. What should we check first?",
        "label": "A transformer is running hotter than the others on the same bus. What should we check first?",
        "note": "The failure on the left is not a hallucination, it is a confident no. That is the expensive one, because nobody goes looking for a second opinion after being told the fault is new.",
    },
    {
        "value": "Card payments are being declined more often than normal. What did we do about it last time?",
        "label": "Card payments are being declined more often than normal. What did we do about it last time?",
        "note": "The question is literally about last time. Keyword search could not find last time, so the model could not either. The model was never the variable here, retrieval was.",
    },
]

POSTGRES_QUERIES = [
    {
        "value": "vibration and noise from a pump at high load",
        "label": "vibration and noise from a pump at high load",
        "note": "There is no vector in this request. The database called the embedding model itself, with its own managed identity.",
    },
    {
        "value": "payments are failing at the checkout",
        "label": "payments are failing at the checkout",
        "note": "Plain English goes in, rows come out. The application never saw a number.",
    },
    {
        "value": "equipment running too hot",
        "label": "equipment running too hot",
        "note": "Same model as Cosmos, half the width, because the index limit differs. That is the constraint, not the database.",
    },
]


GRAPH_QUERIES = [
    {
        "value": "the terminal freezes in the middle of a transaction",
        "label": "the terminal freezes in the middle of a transaction",
        "note": "The checkout terminals are the obvious answer. The vessels and substations are not, and they share no fault code, no component and no domain with the question. They are reached over an edge built from the embeddings, so no JOIN and no WHERE clause could have produced that list.",
    },
    {
        "value": "readings stopped arriving from a remote location",
        "label": "readings stopped arriving from a remote location",
        "note": "Telemetry silence on a substation reads like a store that has gone quiet. Different estate, different fault code, same failure written in the same words.",
    },
    {
        "value": "equipment running too hot",
        "label": "equipment running too hot",
        "note": "The substations come from the fault code. The store comes from the semantic edge. Average hours to fix are already on the row, which turns this from a search result into a maintenance plan.",
    },
    {
        "value": "vibration and noise from a pump at high load",
        "label": "vibration and noise from a pump at high load",
        "note": "Here the semantic edge adds nothing, because every vessel already carries this code. The graph is not magic. It pays off when the connection was not already a column.",
    },
]


CATALOGUE = {
    "keyword": KEYWORD_QUERIES,
    "vector": VECTOR_QUERIES,
    "filtered": FILTERED_QUERIES,
    "hybrid": HYBRID_QUERIES,
    "grounded": GROUNDED_QUESTIONS,
    "postgres": POSTGRES_QUERIES,
    "graph": GRAPH_QUERIES,
}


def note_for(panel: str, value: str) -> str:
    for entry in CATALOGUE.get(panel, []):
        if entry["value"] == value:
            return entry["note"]
    return ""
