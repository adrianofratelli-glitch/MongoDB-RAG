import os
import time
from pymongo import MongoClient
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import voyageai
from dotenv import load_dotenv

load_dotenv()

def ingest_pdf(pdf_path: str):
    client = MongoClient(os.environ["MONGO_URI"])
    collection = client["tjgo_pdtic"]["documents"]

    if collection.count_documents({}) > 0:
        print(f"⚠️  Limpando {collection.count_documents({})} docs anteriores...")
        collection.delete_many({})

    voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])

    print("📄 Carregando PDF...")
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    print(f"   {len(docs)} páginas carregadas")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " "]
    )
    chunks = splitter.split_documents(docs)
    print(f"   {len(chunks)} chunks gerados")

    texts = [c.page_content for c in chunks]
    batch_size = 10  # conservador para free tier (10K TPM)
    docs_to_insert = []

    print("🔢 Gerando embeddings (free tier — ~25 min)...")
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+batch_size]
        batch_chunks = chunks[i:i+batch_size]

        result = voyage.embed(
            batch_texts,
            model="voyage-3",
            input_type="document"
        )

        for j, embedding in enumerate(result.embeddings):
            docs_to_insert.append({
                "text": batch_chunks[j].page_content,
                "embedding": embedding,
                "metadata": {
                    "source": "PDTIC_TJGO_2025_2027",
                    "page": batch_chunks[j].metadata.get("page", 0),
                    "chunk_id": i + j
                }
            })

        progress = min(i + batch_size, len(texts))
        print(f"   {progress}/{len(texts)} chunks | batch {i//batch_size + 1}", end="\r")

        # Rate limit: 3 RPM = 1 req a cada 20s (com margem)
        if i + batch_size < len(texts):
            time.sleep(22)

    print(f"\n💾 Inserindo {len(docs_to_insert)} docs no Atlas...")
    collection.insert_many(docs_to_insert)
    print("✅ Ingestão concluída!")
    client.close()

if __name__ == "__main__":
    ingest_pdf("PDTIC_2025_2027.pdf")
