import os
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
            print(f"✅ Collection criada: {col}")
        else:
            print(f"⏭️  Já existe: {col}")

    # ── Índices Atlas Search (Hybrid Search) ────────────────────────────────────
    docs = db["documents"]
    have = {ix["name"] for ix in docs.list_search_indexes()}

    # Índice vetorial (voyage-3, 1024d) + campo de filtro para ACL
    vector_def = {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine"},
            {"type": "filter", "path": "metadata.nivel_acesso"},
        ]
    }
    if "vector_index" not in have:
        docs.create_search_index({"name": "vector_index", "type": "vectorSearch", "definition": vector_def})
        print("✅ Índice vetorial criado: vector_index (com filtro de ACL)")
    else:
        docs.update_search_index("vector_index", vector_def)
        print("🔄 Índice vetorial atualizado: vector_index (garante filtro de ACL)")

    # Índice léxico (Atlas Search / BM25) para o componente lexical do hybrid
    if "text_index" not in have:
        docs.create_search_index({
            "name": "text_index", "type": "search",
            "definition": {"mappings": {"dynamic": False, "fields": {
                "text": {"type": "string"},
                "metadata": {"type": "document", "fields": {"nivel_acesso": {"type": "token"}}},
            }}},
        })
        print("✅ Índice léxico criado: text_index")
    else:
        print("⏭️  Índice léxico já existe: text_index")

    print(f"\n📊 Collections em '{DB_NAME}':")
    for col in db.list_collection_names():
        print(f"  {col}: {db[col].count_documents({})} docs")

    client.close()
    print("\n✅ Setup concluído!")


if __name__ == "__main__":
    setup()
