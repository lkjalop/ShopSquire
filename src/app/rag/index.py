from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Document:
    doc_id: str
    title: str
    source: str
    tags: List[str]
    content: str
    tenant_allowlist: Optional[List[str]] = None


class DocumentStore:
    def __init__(self, sources_path: str | None = None) -> None:
        self.sources_path = sources_path or os.path.join("src", "app", "rag", "sources", "policy_docs.json")
        self._docs: List[Document] = []
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        docs: List[Document] = []
        try:
            with open(self.sources_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for row in raw:
                docs.append(
                    Document(
                        doc_id=str(row.get("doc_id")),
                        title=row.get("title") or "",
                        source=row.get("source") or "policy",
                        tags=list(row.get("tags") or []),
                        content=row.get("content") or "",
                        tenant_allowlist=row.get("tenant_allowlist"),
                    )
                )
        except Exception:
            docs = []
        self._docs = docs
        self._loaded = True

    def list_documents(self) -> List[Document]:
        self.load()
        return list(self._docs)

    def get_by_id(self, doc_id: str) -> Optional[Document]:
        self.load()
        for doc in self._docs:
            if doc.doc_id == doc_id:
                return doc
        return None
