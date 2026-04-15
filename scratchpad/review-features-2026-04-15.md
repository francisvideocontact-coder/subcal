# Review — commit 012909f → eb19d40
Date : 2026-04-15
Reviewer : agent reviewer (SubCal)

## Verdict final : PASS (après fixes)

---

## Findings

### CRITICAL (2) — corrigés dans eb19d40

| # | Fichier | Ligne | Description |
|---|---|---|---|
| 1 | `engine/normalizer.py` | 30–34 | `'un'`/`'une'` dans le dict → remplace les articles indéfinis ("un film" → "1 film"). Feature inutilisable. |
| 2 | `engine/normalizer.py` | 68–75 | `'cent'` standalone → "pour cent" devient "pour 100". |

**Fixes appliqués :**
- `'un'`/`'une'` retirés du dict (couverts dans les composés : `vingt-et-un`, `quatre-vingt-un`).
- `'cent'` seul retiré (`deux cents`, `trois cents` etc. inchangés).

---

### IMPORTANT (2)

| # | Fichier | Description | Statut |
|---|---|---|---|
| 3 | `web/app.py:304` | Pas de validation Pydantic, `KeyError`/`TypeError` non catchés dans `/api/normalize` | Corrigé : `normalize_blocks()` lève `ValueError`, endpoint retourne HTTP 422 |
| 4 | `tests/` | Aucun test unitaire pour `normalizer.py` — les bugs CRITICAL ont été trouvés manuellement | Non corrigé — à planifier |

---

### MINOR (1) — corrigé dans eb19d40

| # | Fichier | Ligne | Description |
|---|---|---|---|
| 5 | `web/static/app.js` | 806 | `join('')` dans `doReplaceAll` — `['ab','c']` indistinguable de `['a','bc']` |

**Fix :** changé en `join('\n')`.

---

## Manquements process (auto-critique)

- Commit `012909f` poussé **avant** la review → deux bugs CRITICAL en production pendant ~30 min.
- Rapport de review non écrit dans `scratchpad/` immédiatement après le retour de l'agent.

## Tests unitaires manquants (dette)

Cas à couvrir dans `tests/test_normalizer.py` :
- Nombre isolé nominal
- Faux positif article (`un`, `une`)
- `pour cent` non converti
- Composé à trait d'union (`quatre-vingt-dix-neuf`)
- Input vide / `None`
- Bloc mal formé (`KeyError`)
- Forme plurielle (`deux cents`)
