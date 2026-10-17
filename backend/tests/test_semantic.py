from types import SimpleNamespace

import numpy as np
import pytest

from goszakup_ai.core.config import REPO_ROOT
from goszakup_ai.semantic.embedder import MODEL_SUBDIR, Embedder
from goszakup_ai.semantic.subclass import cluster_texts, subclass_rows

MODEL_DIR = REPO_ROOT / "data" / "models"


def unit(*values: float) -> np.ndarray:
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_clusters_are_numbered_by_size() -> None:
    small = [unit(0, 1, 0.01 * i) for i in range(2)]
    large = [unit(1, 0.01 * i, 0) for i in range(3)]

    labels = cluster_texts(np.array(small + large))

    assert labels.tolist() == [1, 1, 0, 0, 0]


def test_single_text_is_its_own_subclass() -> None:
    assert cluster_texts(np.array([unit(1, 0, 0)])).tolist() == [0]


def test_subclass_label_is_the_most_central_text() -> None:
    texts = ["микроскоп", "микроскоп операционный", "операционный микроскоп с камерой"]
    vectors = [unit(1, 0, 0), unit(1, 0.05, 0), unit(1, 0.3, 0)]
    rows = [
        SimpleNamespace(text_key=str(i), text=t, embedding=v)
        for i, (t, v) in enumerate(zip(texts, vectors, strict=True))
    ]

    out = subclass_rows("265161.000.000004", rows)

    assert [r["subclass"] for r in out] == [0, 0, 0]
    assert {r["label"] for r in out} == {"микроскоп операционный"}


@pytest.mark.skipif(
    not (MODEL_DIR / MODEL_SUBDIR / "tokenizer.json").exists(), reason="model not downloaded"
)
def test_embedder_ranks_similar_descriptions() -> None:
    v = Embedder(MODEL_DIR).embed(
        [
            "микроскоп операционный для лор хирургии",
            "стоматологический дентальный микроскоп",
            "игровой набор детский. обучающий микроскоп",
        ]
    )

    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-5)
    assert v[0] @ v[1] > v[0] @ v[2]
