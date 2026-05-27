import os
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv

load_dotenv()

def setup():
    client = MongoClient(os.environ["MONGO_URI"])
    db = client["tjgo_pdtic"]

    collections = ["documents", "checkpoints", "checkpoint_writes"]
    existing = db.list_collection_names()
    
    for col in collections:
        if col not in existing:
            db.create_collection(col)
            print(f"✅ Collection criada: {col}")
        else:
            print(f"⏭️  Já existe: {col}")

    db["checkpoints"].create_index(
        [("thread_id", ASCENDING), ("checkpoint_id", ASCENDING)],
        unique=True, background=True
    )
    db["checkpoint_writes"].create_index(
        [("thread_id", ASCENDING), ("checkpoint_id", ASCENDING)],
        background=True
    )

    print("\n📊 Collections:")
    for col in db.list_collection_names():
        print(f"  {col}: {db[col].count_documents({})} docs")

    client.close()
    print("\n✅ Setup concluído!")

if __name__ == "__main__":
    setup()
