"""Embeddings utility using fastembed (ONNX, no torch/CUDA)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import TextEmbedding

_model: "TextEmbedding | None" = None
EMBEDDING_DIM = 384


def get_embedding_model() -> "TextEmbedding":
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def embed_text(text: str) -> list[float]:
    model = get_embedding_model()
    return list(next(iter(model.embed([text]))))


def warmup_embeddings() -> None:
    model = get_embedding_model()
    list(model.embed(["warmup"]))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    import numpy as np
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))
