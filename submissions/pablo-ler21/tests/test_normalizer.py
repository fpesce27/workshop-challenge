"""Tests del normalizador y SimHash."""

import pytest
from second_brain.normalizer import hamming_distance, normalize, simhash


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

def test_normalize_lowercase():
    assert normalize("HACER 50/50") == normalize("hacer 50/50")


def test_normalize_acentos():
    assert normalize("facturación") == normalize("facturacion")


def test_normalize_sinonimo_mitad():
    # "mitad y mitad" es sinónimo de frase → colapsa directo a "50/50"
    assert normalize("mitad y mitad") == normalize("50/50")
    # "mitad" individual también mapea a "50/50"
    assert normalize("mitad") == normalize("50/50")


def test_normalize_sinonimo_dividir():
    assert normalize("dividir en partes iguales") == normalize("50/50")


def test_normalize_verbo_hacer_removido():
    # "hacer 50/50" y "50/50" deben normalizar igual
    assert normalize("hacer 50/50") == normalize("50/50")


def test_normalize_verbo_armar_removido():
    assert normalize("armar factura a y b") == normalize("factura a y b")


def test_normalize_espacios_colapsados():
    assert normalize("factura   a   y   b") == normalize("factura a y b")


def test_normalize_puntuacion_removida():
    # Puntos, comas, exclamaciones no deben afectar la forma canónica
    result = normalize("factura A, B.")
    assert "," not in result
    assert "." not in result


def test_normalize_preserva_porcentaje():
    result = normalize("70% factura A")
    assert "%" in result


def test_normalize_preserva_barra():
    result = normalize("50/50")
    assert "/" in result


# ---------------------------------------------------------------------------
# SimHash — propiedades de distancia
# ---------------------------------------------------------------------------

def test_simhash_identico():
    h = simhash("armar factura a y b")
    assert hamming_distance(h, h) == 0


def test_simhash_textos_similares_distancia_pequeña():
    h1 = simhash(normalize("armar factura a y b"))
    h2 = simhash(normalize("hacer factura A y B"))
    # Deben ser similares (dist ≤ 3 con umbral del engine)
    assert hamming_distance(h1, h2) <= 3


def test_simhash_textos_distintos_distancia_grande():
    h1 = simhash(normalize("factura a y b"))
    h2 = simhash(normalize("distribuidora sur si mayor 500k"))
    # Textos semánticamente distintos → distancia mayor
    assert hamming_distance(h1, h2) > 3


def test_simhash_50_50_equivalentes():
    # La normalización colapsa las variantes a la misma forma canónica
    h1 = simhash(normalize("50/50"))
    h2 = simhash(normalize("hacer 50/50"))
    assert hamming_distance(h1, h2) == 0  # normalización idéntica → hash idéntico


def test_simhash_es_entero_64_bits():
    h = simhash("cualquier texto")
    assert isinstance(h, int)
    assert 0 <= h <= 0xFFFFFFFFFFFFFFFF


def test_simhash_texto_vacio():
    h = simhash("")
    assert h == 0


# ---------------------------------------------------------------------------
# Hamming distance
# ---------------------------------------------------------------------------

def test_hamming_cero():
    assert hamming_distance(0b1010, 0b1010) == 0


def test_hamming_un_bit():
    assert hamming_distance(0b1010, 0b1011) == 1


def test_hamming_todos_los_bits():
    mask = 0xFFFFFFFFFFFFFFFF
    assert hamming_distance(0, mask) == 64
