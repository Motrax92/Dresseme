import json
import re
from typing import Optional

from schemas import OutfitSuggestionRequest, OutfitSuggestionResponse, WardrobeItemInput

# Harmonies de couleurs simples (base extensible)
COLOR_COMPATIBILITY: dict[str, set[str]] = {
    "noir": {"blanc", "gris", "beige", "bleu", "rouge", "vert", "marron"},
    "blanc": {"noir", "bleu", "beige", "gris", "vert", "rose", "marron"},
    "bleu": {"blanc", "beige", "gris", "marron", "noir"},
    "gris": {"noir", "blanc", "bleu", "rose", "rouge"},
    "beige": {"marron", "blanc", "noir", "bleu", "vert"},
    "marron": {"beige", "blanc", "bleu", "vert"},
}

WEATHER_TO_SEASONS: dict[str, set[str]] = {
    "cold": {"hiver", "automne"},
    "rain": {"automne", "hiver", "printemps"},
    "mild": {"printemps", "automne", "ete", "hiver"},
    "warm": {"ete", "printemps"},
}


def sanitize_text_input(text: str) -> str:
    """Nettoie les entrées libres pour réduire les risques de prompt injection."""
    # Supprime les balises de contrôle ou tentatives d'override classiques
    cleaned = re.sub(r"[\r\n]+", " ", text)
    cleaned = re.sub(
        r"(ignore previous instructions|system prompt|act as|jailbreak)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()[:120]


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def suggest_with_rules(
    items: list[WardrobeItemInput],
    request: OutfitSuggestionRequest,
) -> OutfitSuggestionResponse:
    """Version minimale sans IA : règles de couleurs, météo/saison et >= 3 pièces."""
    allowed_seasons = WEATHER_TO_SEASONS.get(_normalize(request.weather), set())

    # 1. Filtrage doux par saison/météo si renseignée
    scored: list[tuple[int, WardrobeItemInput]] = []
    for item in items:
        score = 0
        item_season = _normalize(item.season)
        if item_season and item_season in allowed_seasons:
            score += 2
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ordered_items = [item for _, item in scored]

    selected: list[WardrobeItemInput] = []
    used_categories: set[str] = set()

    # 2. Priorise la diversité des catégories (ex: haut, bas, chaussures/veste)
    for item in ordered_items:
        cat = _normalize(item.category)
        if cat not in used_categories:
            selected.append(item)
            used_categories.add(cat)
        if len(selected) == 3:
            break

    # 3. Complète jusqu'à 3 pièces en vérifiant la compatibilité couleur
    if len(selected) < 3 and selected:
        base_color = _normalize(selected[0].color)
        compatible = COLOR_COMPATIBILITY.get(base_color, set())
        for item in ordered_items:
            if item.id in {x.id for x in selected}:
                continue
            if not compatible or _normalize(item.color) in compatible:
                selected.append(item)
            if len(selected) == 3:
                break

    # 4. Dernier recours si pas assez de pièces compatibles
    if len(selected) < 3:
        for item in ordered_items:
            if item.id not in {x.id for x in selected}:
                selected.append(item)
            if len(selected) == 3:
                break

    if len(selected) < 3:
        raise ValueError("Il faut au moins 3 vêtements dans la garde-robe pour composer une tenue.")

    names = ", ".join(item.name for item in selected)
    return OutfitSuggestionResponse(
        source="rules_fallback",
        item_ids=[item.id for item in selected],
        justification=(
            f"Tenue composée par règles ({request.weather or 'standard'}) : {names}."
        ),
    )


def _validate_ai_ids(raw_ids: list[int], allowed_ids: set[int]) -> list[int]:
    """Vérifie que les IDs renvoyés par l'IA existent bien chez l'utilisateur (>= 3)."""
    unique_valid: list[int] = []
    for item_id in raw_ids:
        if isinstance(item_id, int) and item_id in allowed_ids and item_id not in unique_valid:
            unique_valid.append(item_id)
    if len(unique_valid) < 3:
        raise ValueError("La suggestion IA ne contient pas au moins 3 pièces valides.")
    return unique_valid


def suggest_outfit(
    items: list[WardrobeItemInput],
    request: OutfitSuggestionRequest,
    llm_caller=None,
) -> OutfitSuggestionResponse:
    """Point d'entrée principal avec garde-fous sécurité et fallback automatique."""
    safe_occasion = sanitize_text_input(request.occasion)
    safe_style = sanitize_text_input(request.style)
    warnings: list[str] = []

    if request.use_ai and request.ai_consent and llm_caller is not None:
        allowed_ids = {item.id for item in items}
        # Payload minimal : uniquement les attributs non sensibles des vêtements[cite: 2]
        minimal_catalog = [
            {
                "id": item.id,
                "category": item.category,
                "color": item.color,
                "season": item.season,
            }
            for item in items
        ]
        prompt_payload = {
            "occasion": safe_occasion,
            "style": safe_style,
            "weather": request.weather,
            "wardrobe": minimal_catalog,
        }
        try:
            raw_response = llm_caller(json.dumps(prompt_payload))
            parsed = json.loads(raw_response)
            valid_ids = _validate_ai_ids(parsed.get("item_ids", []), allowed_ids)
            justification = sanitize_text_input(
                str(parsed.get("justification", "Suggestion générée par IA."))
            )
            return OutfitSuggestionResponse(
                source="ai",
                item_ids=valid_ids,
                justification=justification,
                warnings=warnings,
            )
        except Exception:
            warnings.append("Repli automatique sur le moteur de règles après vérification.")

    if request.use_ai and not request.ai_consent:
        warnings.append("Consentement IA non donné : utilisation des règles locales.")

    fallback = suggest_with_rules(items, request)
    fallback.warnings = warnings + fallback.warnings
    return fallback