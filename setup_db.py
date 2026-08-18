import os
from datetime import timedelta
from pymongo import MongoClient
from config import DB_NAME
from dotenv import load_dotenv

load_dotenv()


def setup() -> None:
    client = MongoClient(os.environ["MONGO_URI"])
    db = client[DB_NAME]

    collections = ["documents", "conversations"]
    existing = db.list_collection_names()

    for col in collections:
        if col not in existing:
            db.create_collection(col)
            print(f"Created collection: {col}")
        else:
            print(f"Already exists: {col}")

    retention_days = max(1, int(os.getenv("CONVERSATION_RETENTION_DAYS", "30")))
    db["conversations"].create_index(
        "updated_at",
        name="updated_at_ttl",
        expireAfterSeconds=int(timedelta(days=retention_days).total_seconds()),
    )

    # Atlas Search indexes (hybrid search)
    docs = db["documents"]
    have = {ix["name"] for ix in docs.list_search_indexes()}

    # Vector index (voyage-3, 1024d) plus a filter field for access control
    vector_def = {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine"},
            {"type": "filter", "path": "metadata.nivel_acesso"},
        ]
    }
    if "vector_index" not in have:
        docs.create_search_index({"name": "vector_index", "type": "vectorSearch", "definition": vector_def})
        print("Created vector index: vector_index (with access-control filter)")
    else:
        docs.update_search_index("vector_index", vector_def)
        print("Updated vector index: vector_index (ensures access-control filter)")

    # Lexical index (Atlas Search / BM25) for the lexical leg of hybrid search
    if "text_index" not in have:
        docs.create_search_index({
            "name": "text_index", "type": "search",
            "definition": {"mappings": {"dynamic": False, "fields": {
                "text": {"type": "string"},
                "metadata": {"type": "document", "fields": {"nivel_acesso": {"type": "token"}}},
            }}},
        })
        print("Created lexical index: text_index")
    else:
        print("Lexical index already exists: text_index")

    print(f"\nCollections in '{DB_NAME}':")
    for col in db.list_collection_names():
        print(f"  {col}: {db[col].count_documents({})} docs")

    client.close()
    print("\nSetup complete.")


if __name__ == "__main__":
    setup()
