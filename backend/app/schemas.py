from typing import Literal, Optional
from pydantic import BaseModel, Field


class WardrobeItemInput(BaseModel):
    """Métadonnées minimales envoyées au moteur/IA (pas d'image ni donnée perso)."""
    id: int
    name: str = Field(..., min_length=1, max_length=100)
    category: str = Field(..., min_length=1, max_length=50)
    color: str = Field(..., min_length=1, max_length=40)
    season: Optional[str] = Field(default=None, max_length=30)
    brand: Optional[str] = Field(default=None, max_length=60)


class OutfitSuggestionRequest(BaseModel):
    occasion: str = Field(..., min_length=2, max_length=120)
    style: str = Field(..., min_length=2, max_length=80)
    budget: Optional[float] = Field(default=None, ge=0, le=100000)
    weather: Optional[Literal["cold", "mild", "warm", "rain"]] = "mild"
    use_ai: bool = True
    ai_consent: bool = False  # Consentement explicite si envoi à un service IA externe


class OutfitSuggestionResponse(BaseModel):
    source: Literal["ai", "rules_fallback"]
    item_ids: list[int] = Field(..., min_length=3)  # Au moins 3 pièces
    justification: str = Field(..., max_length=500)
    warnings: list[str] = Field(default_factory=list)