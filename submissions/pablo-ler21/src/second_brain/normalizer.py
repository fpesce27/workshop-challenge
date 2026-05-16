"""Normalización de texto y SimHash para matching aproximado de observaciones."""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Sinónimos hardcodeados del dominio — mapeo antes de normalizar
# ---------------------------------------------------------------------------
_SYNONYMS: dict[str, str] = {
    # Frases completas primero (se aplican antes que los tokens individuales)
    "dividir en partes iguales": "50/50",
    "partir en partes iguales": "50/50",
    "por partes iguales": "50/50",
    "partes iguales": "50/50",
    "mitad y mitad": "50/50",
    "mitad": "50/50",
    "partir": "split",
    "dividir": "split",
    "dividido": "split",
    "hacer": "",
    "armar": "",
    "realizar": "",
    "emitir": "",
}

# Caracteres que sí son semánticos en este dominio y se preservan
_PRESERVE = re.compile(r"[^a-z0-9/% ]")


def normalize(text: str) -> str:
    """Normaliza una observación a su forma canónica para comparación exacta.

    Pasos: lowercase → quitar acentos → aplicar sinónimos → quitar puntuación
    no semántica → colapsar espacios.
    """
    # Lowercase
    t = text.lower().strip()

    # Quitar acentos (NFD descompone, luego filtramos las marcas diacríticas)
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")

    # Aplicar sinónimos en orden de longitud descendente para evitar
    # reemplazos parciales incorrectos (ej: "partes iguales" antes que "partes")
    for src, dst in sorted(_SYNONYMS.items(), key=lambda x: -len(x[0])):
        t = t.replace(src, dst)

    # Quitar puntuación no semántica (preservar / y %)
    t = _PRESERVE.sub(" ", t)

    # Colapsar espacios múltiples
    t = re.sub(r"\s+", " ", t).strip()

    return t


# ---------------------------------------------------------------------------
# SimHash de 64 bits sobre bigramas de palabras
# ---------------------------------------------------------------------------

def _bigrams(words: list[str]) -> list[str]:
    """Genera bigramas de una lista de palabras."""
    if len(words) < 2:
        return words  # unigrama como fallback si hay una sola palabra
    return [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]


def _fnv1a_64(s: str) -> int:
    """FNV-1a 64-bit hash — rápido, sin dependencias externas."""
    FNV_PRIME = 0x00000100000001B3
    FNV_OFFSET = 0xCBF29CE484222325
    h = FNV_OFFSET
    for byte in s.encode("utf-8"):
        h ^= byte
        h = (h * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def simhash(text_normalized: str) -> int:
    """Calcula el SimHash de 64 bits de un texto ya normalizado.

    Usa bigramas de palabras como features. Devuelve un entero de 64 bits.
    Dos textos similares producen SimHashes con distancia de Hamming pequeña.
    """
    words = text_normalized.split()
    if not words:
        return 0

    features = _bigrams(words)

    # Vector de acumulación: 64 posiciones, cada una suma +1 o -1
    vector = [0] * 64

    for feature in features:
        h = _fnv1a_64(feature)
        for i in range(64):
            # Si el bit i está en 1, suma +1; si no, -1
            if (h >> i) & 1:
                vector[i] += 1
            else:
                vector[i] -= 1

    # Colapsar: si la posición es positiva → bit 1, si no → bit 0
    result = 0
    for i in range(64):
        if vector[i] > 0:
            result |= 1 << i

    return result


def hamming_distance(a: int, b: int) -> int:
    """Cuenta los bits distintos entre dos SimHashes de 64 bits."""
    xor = (a ^ b) & 0xFFFFFFFFFFFFFFFF
    # Algoritmo de Kernighan: cuenta bits en 1 en O(bits en 1)
    count = 0
    while xor:
        xor &= xor - 1
        count += 1
    return count


def to_db_int(h: int) -> int:
    """Convierte un SimHash unsigned 64-bit a signed para almacenar en SQLite."""
    if h >= (1 << 63):
        return h - (1 << 64)
    return h


def from_db_int(h: int) -> int:
    """Recupera el unsigned 64-bit original desde el valor signed de SQLite."""
    return h & 0xFFFFFFFFFFFFFFFF
