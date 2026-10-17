from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path

import httpx
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

log = logging.getLogger(__name__)

MODEL_REPO = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_FILES = {
    "onnx/model_qint8_avx512_vnni.onnx": (
        "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"
    ),
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
}
MODEL_ID = f"{MODEL_REPO}@{MODEL_REVISION[:8]}/qint8"
MODEL_SUBDIR = f"multilingual-e5-small-{MODEL_REVISION[:8]}"
DIM = 384
MAX_TOKENS = 128
PREFIX = "query: "


def ensure_model(model_dir: Path) -> Path:
    root = model_dir / MODEL_SUBDIR
    for name, sha256 in MODEL_FILES.items():
        path = root / Path(name).name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}"
        log.info("downloading %s", url)
        digest = hashlib.sha256()
        part = path.with_name(path.name + ".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with part.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    digest.update(chunk)
                    f.write(chunk)
        if digest.hexdigest() != sha256:
            part.unlink()
            raise RuntimeError(f"checksum mismatch for {url}")
        part.rename(path)
    return root


class Embedder:
    def __init__(self, model_dir: Path) -> None:
        root = ensure_model(model_dir)
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        self.session = ort.InferenceSession(
            str(root / "model_qint8_avx512_vnni.onnx"), providers=["CPUExecutionProvider"]
        )

    def embed(self, texts: Sequence[str], batch_size: int = 64) -> np.ndarray:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        for start in range(0, len(order), batch_size):
            idx = order[start : start + batch_size]
            encoded = self.tokenizer.encode_batch([PREFIX + texts[i] for i in idx])
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            hidden = self.session.run(
                None,
                {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)},
            )[0]
            pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            out[idx] = pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
        return out
