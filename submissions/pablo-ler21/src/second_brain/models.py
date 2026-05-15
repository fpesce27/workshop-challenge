"""Modelos Pydantic del sistema Second Brain."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Acciones ejecutables — el "mini-programa" que vive dentro de una regla
# ---------------------------------------------------------------------------

class Condition(BaseModel):
    """Condición evaluable para una acción condicional."""
    field: Literal["amount", "date", "day_of_week"] = "amount"
    operator: Literal["gt", "gte", "lt", "lte", "eq"] = "gt"
    value: Union[float, str]


class SplitInvoiceAction(BaseModel):
    """Partir una factura en tipo A y tipo B según porcentaje."""
    type: Literal["split_invoice"] = "split_invoice"
    type_a_pct: int = Field(ge=0, le=100)
    type_b_pct: int = Field(ge=0, le=100)

    def model_post_init(self, __context: object) -> None:
        if self.type_a_pct + self.type_b_pct != 100:
            raise ValueError("type_a_pct + type_b_pct debe sumar 100")


class MultiTaxIDAction(BaseModel):
    """Elegir razón social / CUIT según condiciones (ej: monto, fecha)."""
    type: Literal["multi_tax_id"] = "multi_tax_id"
    default_cuit: str
    conditions: list[Condition] = Field(default_factory=list)
    condition_cuit: Optional[str] = None


class LiteralInstructionAction(BaseModel):
    """Instrucción en lenguaje natural — fallback cuando no se pudo estructurar."""
    type: Literal["literal_instruction"] = "literal_instruction"
    natural_language: str


# Unión discriminada de todas las acciones posibles
Action = Union[SplitInvoiceAction, MultiTaxIDAction, LiteralInstructionAction]


# ---------------------------------------------------------------------------
# Regla compilada
# ---------------------------------------------------------------------------

class Rule(BaseModel):
    """Regla compilada y almacenada en SQLite."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope: Literal["client", "global"]
    client_id: Optional[str] = None
    pattern_canonical: str
    pattern_simhash: int
    action: Action
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    hit_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_used_at: Optional[datetime] = None
    last_modified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["active", "shadow", "deprecated", "archived"] = "shadow"


# ---------------------------------------------------------------------------
# Observación cruda entrante
# ---------------------------------------------------------------------------

class Observation(BaseModel):
    """Input crudo de un comprobante: el texto de la sección observaciones."""
    client_id: str
    text: str
    comprobante_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Resultado de una búsqueda en el motor
# ---------------------------------------------------------------------------

class RuleMatch(BaseModel):
    """Resultado del lookup en el motor de reglas."""
    rule: Optional[Rule] = None
    match_type: Literal["exact", "simhash", "semantic", "none"] = "none"
    match_score: float = Field(ge=0.0, le=1.0, default=0.0)


# ---------------------------------------------------------------------------
# Request de compilación asíncrona
# ---------------------------------------------------------------------------

class CompilationRequest(BaseModel):
    """Job encolado para compilar la respuesta del usuario en una regla."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    observation: Observation
    user_response: str
    original_rule_id: Optional[str] = None  # si era corrección de una regla existente
    retry_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
