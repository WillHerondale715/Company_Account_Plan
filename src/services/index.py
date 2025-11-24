
import os
import numpy as np
import logging
from typing import List, Dict, Tuple
from dotenv import load_dotenv
from openai import OpenAI

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
logger = logging.getLogger("index-service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s')

# ------------------------------------------------------------------------------
# Environment & OpenAI client
# ------------------------------------------------------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


class VectorIndex:
    def __init__(self):
        self.vectors = None
        self.metadatas: List[Dict] = []
        self.texts: List[str] = []
        self.dim = None

    def _embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for given texts, fallback to random if API fails."""
        if not client:
            logger.warning("[embed] No OpenAI client. Using random embeddings.")
            rng = np.random.default_rng(42)
            self.dim = 512
            return rng.random((len(texts), self.dim))

        try:
            resp = client.embeddings.create(model=OPENAI_EMBED_MODEL, input=texts)
            embs = [e.embedding for e in resp.data]
            self.dim = len(embs[0])
            return np.array(embs, dtype=np.float32)
        except Exception as e:
            logger.warning(f"[embed] OpenAI API failed: {e}. Using random embeddings.")
            rng = np.random.default_rng(42)
            self.dim = 512
            return rng.random((len(texts), self.dim))

    def add(self, texts: List[str], metadatas: List[Dict]):
        """Add texts and their metadata to the index."""
        if not texts:
            logger.warning("[add] No texts provided.")
            return
        embeds = self._embed(texts)
        self.texts.extend(texts)
        self.metadatas.extend(metadatas)
        self.vectors = embeds if self.vectors is None else np.vstack([self.vectors, embeds])
        logger.info(f"[add] Added {len(texts)} items. Total size: {len(self.texts)}")

    def search(self, query: str, k: int = 5) -> List[Tuple[float, Dict]]:
        """Return top-k results as (similarity, metadata)."""
        if self.vectors is None or len(self.texts) == 0:
            logger.warning("[search] Index is empty.")
            return []
        qv = self._embed([query])[0]
        denom = np.linalg.norm(self.vectors, axis=1) * np.linalg.norm(qv)
        sims = (self.vectors @ qv) / (denom + 1e-8)
        idxs = np.argsort(-sims)[:k]
        return [(float(sims[i]), self.metadatas[i]) for i in idxs]
