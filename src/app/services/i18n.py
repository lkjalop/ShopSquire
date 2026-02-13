from __future__ import annotations

from typing import Any, Dict


SUPPORTED_LOCALES = {"en", "en-us", "en-gb", "es", "fr"}


def normalize_locale(locale: str | None) -> str:
    raw = str(locale or "").strip().lower()
    if not raw:
        return "en"
    if raw in SUPPORTED_LOCALES:
        return raw
    if raw.startswith("es"):
        return "es"
    if raw.startswith("fr"):
        return "fr"
    return "en"


_TEMPLATES = {
    "es": {
        "unsupported_catalog": "No encontre una coincidencia confiable en el catalogo actual, por eso no sugiero productos no relacionados.",
        "clarify": "Para recomendar mejor: presupuesto, uso principal y marcas preferidas.",
        "question_budget": "Cual es tu rango de presupuesto?",
        "question_use_case": "Para que lo usaras principalmente?",
        "question_brand": "Tienes preferencia de marca?",
    },
    "fr": {
        "unsupported_catalog": "Je n'ai pas trouve de correspondance fiable dans le catalogue, donc je n'ajoute pas de produits hors sujet.",
        "clarify": "Pour mieux recommander: budget, usage principal et marques preferees.",
        "question_budget": "Quelle est votre plage de budget?",
        "question_use_case": "Quel sera votre usage principal?",
        "question_brand": "Avez-vous une preference de marque?",
    },
}


def localize_recommend_payload(payload: Dict[str, Any], locale: str | None) -> Dict[str, Any]:
    out = dict(payload or {})
    loc = normalize_locale(locale)
    if loc == "en":
        return out
    t = _TEMPLATES.get(loc) or {}
    status = str(out.get("status") or "")
    if status == "unsupported_request":
        out["assistant_message"] = t.get("unsupported_catalog", out.get("assistant_message"))
    elif status == "clarifying_questions":
        out["assistant_message"] = t.get("clarify", out.get("assistant_message"))
    # Localize lightweight question prompts for demo readability.
    nqs = out.get("next_questions")
    if isinstance(nqs, list):
        mapped = []
        for q in nqs:
            if not isinstance(q, dict):
                mapped.append(q)
                continue
            qq = dict(q)
            txt = str(qq.get("text") or "").lower()
            if "budget" in txt:
                qq["text"] = t.get("question_budget", qq.get("text"))
            elif "use" in txt or "primarily" in txt:
                qq["text"] = t.get("question_use_case", qq.get("text"))
            elif "brand" in txt:
                qq["text"] = t.get("question_brand", qq.get("text"))
            mapped.append(qq)
        out["next_questions"] = mapped
    out["locale"] = loc
    return out

