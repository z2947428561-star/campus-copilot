"""Native vector adapters: read paths never create a database or collection."""
from contextlib import contextmanager
import math

from langchain_core.documents import Document

import config
from kb_releases import absolute_path


def checked_vectors(vectors, count):
    if len(vectors) != count:
        raise ValueError("Embedding count differs from input count")
    for vector in vectors:
        if len(vector) != config.EMBED_DIM or not all(math.isfinite(v) for v in vector) or not any(vector):
            raise ValueError("Embedding dimension, finite values or norm is invalid")
    return vectors


@contextmanager
def milvus(*, create=False):
    from pymilvus import MilvusClient
    client = MilvusClient(uri=config.MILVUS_URI, **({} if create else {"db_name": config.MILVUS_DB_NAME}), timeout=10)
    try:
        if create:
            if config.MILVUS_DB_NAME not in client.list_databases():
                client.create_database(db_name=config.MILVUS_DB_NAME)
            client.use_database(db_name=config.MILVUS_DB_NAME)
        yield client
    finally:
        client.close()


def chroma(*, create=False):
    import chromadb
    path = absolute_path(config.CHROMA_DIR)
    if not create and not (path / "chroma.sqlite3").is_file():
        raise ValueError("No existing Chroma index")
    return chromadb.PersistentClient(path=str(path))


def create_collection(name):
    if config.KB_BACKEND == "chroma":
        chroma(create=True).create_collection(name, embedding_function=None, metadata={"hnsw:space": "cosine"})
        return
    from pymilvus import DataType, MilvusClient
    with milvus(create=True) as client:
        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=config.EMBED_DIM)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        indexes = client.prepare_index_params()
        indexes.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        client.create_collection(collection_name=name, schema=schema, index_params=indexes)


def add(name, documents, vectors, offset):
    if config.KB_BACKEND == "chroma":
        chroma().get_collection(name, embedding_function=None).add(
            ids=[str(offset + i) for i in range(len(documents))],
            embeddings=vectors, documents=[d.page_content for d in documents],
            metadatas=[d.metadata or {"chunk_id": offset + i} for i, d in enumerate(documents)])
        return
    with milvus() as client:
        client.insert(collection_name=name, data=[
            {**d.metadata, "text": d.page_content, "vector": v} for d, v in zip(documents, vectors)])


def finish(name):
    if config.KB_BACKEND == "milvus":
        with milvus() as client:
            client.flush(collection_name=name)
            client.load_collection(collection_name=name)


def count(name):
    if config.KB_BACKEND == "chroma":
        return chroma().get_collection(name, embedding_function=None).count()
    with milvus() as client:
        return int(client.query(collection_name=name, filter="", output_fields=["count(*)"],
                                consistency_level="Strong")[0]["count(*)"])


def check_collection(name):
    if config.KB_BACKEND == "chroma":
        collection = chroma().get_collection(name, embedding_function=None)
        if (collection.metadata or {}).get("hnsw:space") != "cosine":
            raise ValueError("Index must use COSINE")
    else:
        with milvus() as client:
            description = client.describe_collection(collection_name=name)
            vector = next((f for f in description["fields"] if f["name"] == "vector"), {})
            if int(vector.get("params", {}).get("dim", 0)) != config.EMBED_DIM:
                raise ValueError("Index vector dimension differs")
            indexes = client.list_indexes(collection_name=name, field_name="vector")
            if not indexes or client.describe_index(collection_name=name, index_name=indexes[0]).get("metric_type", "").upper() != "COSINE":
                raise ValueError("Index must use COSINE")


class Reader:
    def __init__(self, name, embeddings):
        self.name = name
        self.embeddings = embeddings

    def similarity_search_with_score(self, query, k=5, *, filter=None, expr=None):
        vector = checked_vectors([self.embeddings.embed_query(query)], 1)[0]
        if config.KB_BACKEND == "chroma":
            collection = chroma().get_collection(self.name, embedding_function=None)
            limit = min(k, collection.count())
            if not limit:
                return []
            args = {"where": filter} if filter else {}
            result = collection.query(query_embeddings=[vector], n_results=limit,
                                      include=["documents", "metadatas", "distances"], **args)
            return [(Document(page_content=text, metadata=meta or {}), float(score)) for text, meta, score in
                    zip(result["documents"][0], result["metadatas"][0], result["distances"][0])]
        with milvus() as client:
            hits = client.search(collection_name=self.name, data=[vector], anns_field="vector", limit=k,
                                 filter=expr or "", output_fields=["*"], consistency_level="Strong",
                                 search_params={"metric_type": "COSINE", "params": {}})[0]
        output = []
        for hit in hits:
            entity = dict(hit["entity"])
            text = entity.pop("text", "")
            entity.pop("vector", None)
            output.append((Document(page_content=text, metadata=entity), float(hit["distance"])))
        return output

    def similarity_search_with_relevance_scores(self, query, k=5, **kwargs):
        return [(doc, (score + 1) / 2 if config.KB_BACKEND == "milvus" else 1 - score / 2)
                for doc, score in self.similarity_search_with_score(query, k=k, **kwargs)]
