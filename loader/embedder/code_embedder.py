import logging
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim output, 512-token input limit
# Functions longer than 512 tokens (~1500 chars) are truncated by the model.
# This is acceptable — the vast majority of functions are well under this limit.


class CodeEmbedder:
    def __init__(self):
        logger.info(f"Loading embedding model: {MODEL_NAME} ...")
        self.model = SentenceTransformer(MODEL_NAME)

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(
            texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False
        ).tolist()
