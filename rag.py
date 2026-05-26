"""
Local copy of RAG helper (simplified).
The original uses OpenAI embeddings; this copy keeps the load_cases helper and simple retrieval stub.
"""
import json
from pathlib import Path
from typing import List, Dict, Any

_BASE_DIR = Path(__file__).parent / "knowledge_base"
_CASES_DIR = _BASE_DIR / "cases"

def load_cases() -> List[Dict[str, Any]]:
    if not _CASES_DIR.exists():
        return []
    cases = []
    for md in sorted(_CASES_DIR.glob("*.md")):
        content = md.read_text(encoding="utf-8")
        cases.append({"id": md.stem, "title": md.stem, "content": content, "body": content})
    return cases

async def retrieve_cases(query: str, api_key: str, top_k: int = 5, threshold: float = 0.25):
    # Simplified: return metadata of cases (no embeddings)
    cases = load_cases()
    return cases[:top_k]

def get_cases_metadata():
    cases = load_cases()
    return [{"id": c["id"], "title": c["title"]} for c in cases]
