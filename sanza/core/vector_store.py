import os
import numpy as np
from django.conf import settings

class VectorStore:
    def __init__(self):
        self.index_path = os.path.join(settings.BASE_DIR, 'sanza/data/faiss.index')
        self.meta_path = os.path.join(settings.BASE_DIR, 'sanza/data/faiss_meta.pkl')
        self.dimension = 384
        self._index = None        # Lazy load
        self._metadata = None     # Lazy load

    @property
    def index(self):
        if self._index is None:
            self._load_or_create()
        return self._index

    @property
    def metadata(self):
        if self._metadata is None:
            self._load_or_create()
        return self._metadata

    @metadata.setter
    def metadata(self, value):
        self._metadata = value

    def _load_or_create(self):
        import faiss
        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            try:
                self._index = faiss.read_index(self.index_path)
                import pickle
                with open(self.meta_path, 'rb') as f:
                    self._metadata = pickle.load(f)
            except Exception:
                self._create_new()
        else:
            self._create_new()

    def _create_new(self):
        import faiss
        self._index = faiss.IndexFlatIP(self.dimension)
        self._metadata = []

    def add(self, embeddings, metadata_list):
        if len(embeddings) == 0:
            return
        embeddings = np.array(embeddings).astype('float32')
        self.index.add(embeddings)
        self.metadata.extend(metadata_list)
        self._save()

    def search(self, query_embedding, top_k=5):
        if self.index.ntotal == 0:
            return []
        query_embedding = np.array([query_embedding]).astype('float32')
        scores, indices = self.index.search(query_embedding, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx != -1 and score > 0.3:
                try:
                    meta = self.metadata[idx].copy()
                    meta['score'] = float(score)
                    results.append(meta)
                except IndexError:
                    continue
        return results

    def rebuild(self, embeddings, metadata_list):
        self._create_new()
        self.add(embeddings, metadata_list)

    def _save(self):
        import faiss
        import pickle
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, 'wb') as f:
            pickle.dump(self.metadata, f)