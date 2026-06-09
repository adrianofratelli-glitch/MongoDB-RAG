import os
import sys
import time
import argparse
from pathlib import Path
from pymongo import MongoClient
from langchain_text_splitters import RecursiveCharacterTextSplitter
import voyageai
from config import DB_NAME, CLIENT_ID
from dotenv import load_dotenv

load_dotenv()

SUPPORTED_FORMATS = {".pdf", ".docx", ".doc", ".txt", ".csv"}


def get_loader(file_path: str):
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        return PyPDFLoader(file_path)
    if ext in (".docx", ".doc"):
        from langchain_community.document_loaders import Docx2txtLoader
        return Docx2txtLoader(file_path)
    if ext == ".txt":
        from langchain_community.document_loaders import TextLoader
        return TextLoader(file_path, encoding="utf-8")
    if ext == ".csv":
        from langchain_community.document_loaders import CSVLoader
        return CSVLoader(file_path)
    raise ValueError(
        f"Formato não suportado: '{ext}'. "
        f"Formatos aceitos: {', '.join(sorted(SUPPORTED_FORMATS))}"
    )


def ingest(file_path: str, reset: bool = False, nivel_acesso: str = "publico") -> None:
    path = Path(file_path)
    if not path.exists():
        print(f"❌ Arquivo não encontrado: {file_path}")
        sys.exit(1)

    client = MongoClient(os.environ["MONGO_URI"])
    collection = client[DB_NAME]["documents"]

    source_name = path.stem
    existing = collection.count_documents({"metadata.source": source_name})

    if existing > 0 and not reset:
        print(
            f"⚠️  '{source_name}' já está indexado ({existing} chunks). "
            "Use --reset para reindexar."
        )
        client.close()
        return

    if reset and existing > 0:
        print(f"🗑️  Removendo {existing} chunks de '{source_name}'...")
        collection.delete_many({"metadata.source": source_name})

    voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])

    print(f"📄 Carregando {path.name}...")
    loader = get_loader(file_path)
    docs = loader.load()
    print(f"   {len(docs)} páginas/seções carregadas")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " "],
    )
    chunks = splitter.split_documents(docs)
    print(f"   {len(chunks)} chunks gerados")

    texts = [c.page_content for c in chunks]
    batch_size = 10  # conservador para free tier (10K TPM)
    docs_to_insert = []

    print("🔢 Gerando embeddings (free tier — ~25 min para documentos grandes)...")
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        batch_chunks = chunks[i : i + batch_size]

        result = voyage.embed(batch_texts, model="voyage-3", input_type="document")

        for j, embedding in enumerate(result.embeddings):
            docs_to_insert.append({
                "text": batch_chunks[j].page_content,
                "embedding": embedding,
                "metadata": {
                    "source": source_name,
                    "client_id": CLIENT_ID,
                    "file": path.name,
                    "page": batch_chunks[j].metadata.get("page", 0),
                    "chunk_id": i + j,
                    # ACL: nível de acesso usado no filtro do $vectorSearch / Atlas Search.
                    "nivel_acesso": nivel_acesso,
                },
            })

        progress = min(i + batch_size, len(texts))
        print(f"   {progress}/{len(texts)} chunks | batch {i // batch_size + 1}", end="\r")

        # Rate limit: 3 RPM = 1 req a cada 20s (com margem)
        if i + batch_size < len(texts):
            time.sleep(22)

    print(f"\n💾 Inserindo {len(docs_to_insert)} docs no Atlas (DB: {DB_NAME})...")
    collection.insert_many(docs_to_insert)
    print("✅ Ingestão concluída!")
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingesta documentos no RAG (PDF, DOCX, TXT, CSV)"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="data/documento.pdf",
        help="Caminho para o arquivo a indexar",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Remove chunks existentes e re-indexa o documento",
    )
    parser.add_argument(
        "--nivel",
        choices=["publico", "restrito"],
        default="publico",
        help="Nível de acesso (ACL) atribuído aos chunks deste documento",
    )
    args = parser.parse_args()
    ingest(args.file, reset=args.reset, nivel_acesso=args.nivel)
