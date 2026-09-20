"""Foundry clients: one credential, one embeddings client, one chat client.

Three consumers share this single Foundry account during the demo: the app's
embedding calls, the app's chat calls, and PostgreSQL itself through its managed
identity. That last one never appears in this file, which is the point.
"""

from __future__ import annotations

import functools

from azure.ai.inference import ChatCompletionsClient, EmbeddingsClient
from azure.identity import AzureCliCredential

from . import config


@functools.lru_cache(maxsize=1)
def credential() -> AzureCliCredential:
    # AzureDeveloperCliCredential is not used: azd is not working on this machine.
    return AzureCliCredential()


@functools.lru_cache(maxsize=1)
def embeddings_client() -> EmbeddingsClient:
    return EmbeddingsClient(
        endpoint=config.FOUNDRY_MODELS_ENDPOINT,
        credential=credential(),
        credential_scopes=[config.COGNITIVE_SCOPE],
    )


@functools.lru_cache(maxsize=1)
def chat_client() -> ChatCompletionsClient:
    return ChatCompletionsClient(
        endpoint=config.FOUNDRY_MODELS_ENDPOINT,
        credential=credential(),
        credential_scopes=[config.COGNITIVE_SCOPE],
        api_version="2024-05-01-preview",
    )


def embed(texts: list[str], dimensions: int, model: str | None = None) -> list[list[float]]:
    # text-embedding-3-large supports Matryoshka truncation, so a shorter vector
    # is a prefix of the same embedding rather than a different model's output.
    response = embeddings_client().embed(
        input=texts, model=model or config.EMBEDDING_MODEL, dimensions=dimensions
    )
    return [item.embedding for item in response.data]


def embed_one(text: str, dimensions: int = config.COSMOS_DIMS) -> list[float]:
    return embed([text], dimensions)[0]
