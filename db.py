"""Shared MongoDB client (singleton).

PyMongo's MongoClient keeps an internal connection pool and is thread-safe.
Creating a client per request discards that pool and adds handshake/TLS
latency to every call, so always reuse this instance.
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
