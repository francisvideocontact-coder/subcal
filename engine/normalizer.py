"""
engine/normalizer.py — Conversion des nombres français écrits en chiffres.

Exemples :
  "j'ai quatorze ans"          → "j'ai 14 ans"
  "quatre-vingt-dix-neuf"      → "99"
  "deux mille vingt-quatre"    → n/a (non supporté, traité mot par mot)
  "deux mille"                 → "2000"
"""
from __future__ import annotations

import copy
import re
from typing import Dict, List


# ── Dictionnaire ────────────────────────────────────────────────────────────

def _build_number_dict() -> Dict[str, int]:
    """Construit un mapping complet mot → valeur pour les nombres français."""
    units: List[str] = [
        'zéro', 'un', 'deux', 'trois', 'quatre', 'cinq',
        'six', 'sept', 'huit', 'neuf', 'dix', 'onze',
        'douze', 'treize', 'quatorze', 'quinze', 'seize',
        'dix-sept', 'dix-huit', 'dix-neuf',
    ]

    d: Dict[str, int] = {}

    # 0, 2–19 — 'un'/'une' délibérément exclus : ce sont aussi des articles
    # indéfinis ("un film", "une journée") qui produiraient des faux positifs massifs.
    for i, w in enumerate(units):
        if i == 1:   # skip 'un'
            continue
        d[w] = i
    d['zero'] = 0   # variant sans accent

    # 20–69 (dizaines simples + composés)
    simple_tens = [
        (20, 'vingt'), (30, 'trente'), (40, 'quarante'),
        (50, 'cinquante'), (60, 'soixante'),
    ]
    for val, word in simple_tens:
        d[word] = val
        d[f'{word}-et-un'] = val + 1
        d[f'{word}-et-une'] = val + 1
        for i in range(2, 10):
            d[f'{word}-{units[i]}'] = val + i

    # 70–79 (soixante-dix…)
    d['soixante-dix'] = 70
    d['soixante-et-onze'] = 71
    d['soixante-onze'] = 71
    for i in range(2, 10):
        d[f'soixante-dix-{units[i]}'] = 70 + i
    for i in range(12, 20):
        d[f'soixante-{units[i]}'] = 60 + i   # soixante-douze=72, …

    # 80–99 (quatre-vingt…)
    d['quatre-vingts'] = 80
    d['quatre-vingt'] = 80
    d['quatre-vingt-un'] = 81
    d['quatre-vingt-une'] = 81
    for i in range(2, 10):
        d[f'quatre-vingt-{units[i]}'] = 80 + i
    for i in range(10, 20):
        d[f'quatre-vingt-{units[i]}'] = 80 + i

    # Centaines rondes — 'cent' seul exclu pour éviter "pour cent" → "pour 100"
    hundreds_prefixes = [
        '', '', 'deux cents', 'trois cents', 'quatre cents',
        'cinq cents', 'six cents', 'sept cents', 'huit cents', 'neuf cents',
    ]
    for i, prefix in enumerate(hundreds_prefixes):
        if prefix:
            d[prefix] = i * 100

    # Milliers courants
    d['mille'] = 1_000
    for i in range(2, 10):
        d[f'{units[i]} mille'] = i * 1_000
    d['dix mille'] = 10_000
    d['cent mille'] = 100_000

    # Grands nombres
    d['un million'] = 1_000_000
    d['million'] = 1_000_000
    d['un milliard'] = 1_000_000_000
    d['milliard'] = 1_000_000_000

    return d


_NUMBER_DICT: Dict[str, int] = _build_number_dict()

# Trié longueur décroissante → la plus longue correspondance est essayée en premier
_SORTED_WORDS: List[str] = sorted(_NUMBER_DICT.keys(), key=len, reverse=True)

# Regex unique : alternance ordonnée, insensible à la casse
_MASTER_RE = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in _SORTED_WORDS) + r')\b',
    re.IGNORECASE,
)


# ── API publique ─────────────────────────────────────────────────────────────

def normalize_numbers(text: str) -> str:
    """Remplace les nombres écrits en français par leurs chiffres dans un texte."""
    def _rep(m: re.Match) -> str:  # type: ignore[type-arg]
        key = m.group(1).lower()
        return str(_NUMBER_DICT.get(key, m.group(1)))
    return _MASTER_RE.sub(_rep, text)


def normalize_blocks(blocks: list) -> list:
    """
    Applique normalize_numbers() sur chaque ligne de chaque bloc.
    Retourne une copie profonde avec les métriques recalculées.
    Lève ValueError si un bloc est mal formé.
    """
    if not isinstance(blocks, list):
        raise ValueError("blocks doit être une liste")
    result = copy.deepcopy(blocks)
    for block in result:
        if not isinstance(block, dict) or 'lines' not in block:
            raise ValueError(f"Bloc mal formé (clé 'lines' manquante) : {block!r:.100}")
        new_lines = [normalize_numbers(line) for line in block['lines']]
        if new_lines != block['lines']:
            block['lines'] = new_lines
            block['text'] = ' '.join(new_lines)
            block['modified'] = True
            # Recalcul des métriques
            dur_s = block.get('duration_s') or 0
            total_chars = sum(len(ln) for ln in new_lines)
            block['cps'] = round(total_chars / dur_s, 1) if dur_s > 0 else 0.0
            block['cpl_per_line'] = [len(ln) for ln in new_lines]
            block['cpl_max'] = max(block['cpl_per_line']) if block['cpl_per_line'] else 0
    return result
