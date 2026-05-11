import numpy as np
from sentence_transformers import SentenceTransformer

class EmbeddingEngine:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingEngine, cls).__new__(cls)
            cls._instance.model = SentenceTransformer('all-MiniLM-L6-v2')
        return cls._instance

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.array([])
        return self.model.encode(texts, normalize_embeddings=True)

    def embed_single(self, text: str) -> np.ndarray:
        if not text:
            return np.zeros(384) # Dim for all-MiniLM-L6-v2
        return self.model.encode([text], normalize_embeddings=True)[0]
