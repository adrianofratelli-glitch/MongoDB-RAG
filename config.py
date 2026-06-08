import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID", "default")
CLIENT_NAME = os.getenv("CLIENT_NAME", "Assistente")
DOCUMENT_TITLE = os.getenv("DOCUMENT_TITLE", "Base de Conhecimento")
DOCUMENT_DESCRIPTION = os.getenv("DOCUMENT_DESCRIPTION", "Converse com seus documentos corporativos.")
DB_NAME = os.getenv("DB_NAME", f"rag_{CLIENT_ID}")
SYSTEM_PROMPT_EXTRA = os.getenv("SYSTEM_PROMPT_EXTRA", "")

_cfg_path = Path("client_config.json")
_cfg: dict = json.loads(_cfg_path.read_text(encoding="utf-8")) if _cfg_path.exists() else {}

QUESTIONS: list[str] = _cfg.get("questions", [
    "📋 O que este documento aborda?",
    "🎯 Quais são os principais objetivos?",
    "📅 Quais são os prazos mais importantes?",
    "💡 Quais são as principais recomendações?",
    "💰 Quais são os custos ou investimentos previstos?",
    "🔐 Quais são os requisitos de segurança?",
    "🏗️ Quais projetos de infraestrutura estão previstos?",
    "📊 Quais são as métricas e indicadores de sucesso?",
])

FOLLOWUPS: dict[str, list[str]] = _cfg.get("followups", {})

DEFAULT_FOLLOWUPS = [
    "📋 Pode detalhar mais sobre este tema?",
    "🗓️ Quais são os próximos passos relacionados?",
]
