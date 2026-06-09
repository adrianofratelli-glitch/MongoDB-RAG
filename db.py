"""Cliente MongoDB compartilhado (singleton).

O MongoClient do PyMongo mantém um pool de conexões interno e é thread-safe;
criar um cliente por requisição descarta o pool e adiciona latência de
handshake/TLS a cada chamada. Reutilize sempre esta instância.
"""
import os

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(os.environ["MONGO_URI"], serverSelectionTimeoutMS=3500)
    return _client
