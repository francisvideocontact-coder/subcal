# Plan — Nouvelles fonctionnalités SubCal
Date : 2026-04-11

## 3 features à implémenter

### 1. Normalisation des nombres (français écrits → chiffres)
- `engine/normalizer.py` : dict complet 0-99 + centaines/milliers rondes, regex alternance triée par longueur
- `web/app.py` : endpoint `POST /api/normalize` (reçoit blocks JSON, retourne blocks corrigés)
- `web/templates/index.html` : bouton "Normaliser chiffres" dans sidebar-actions
- `web/static/app.js` : `doNormalize()` — appelle API, pushHistory, met à jour S.blocks

### 2. Recherche / Remplacement global
- Pure JS (pas d'API nécessaire)
- Barre collapsible entre block-list-header et block-list
- Inputs : recherche + remplacement + bouton "Remplacer" + compteur d'occurrences
- Toggle : bouton ⌕ dans block-list-header + raccourci ⌘F
- `doReplaceAll()` : pushHistory() avant, regexp, re-render

### 3. Preview redimensionnable
- CSS : `.preview-frame` passe de fixed px à `width:100%; aspect-ratio: 16/9`
- Slider `cfg-preview-width` dans right sidebar (220–600px) contrôle `--right-w`
- Le preview scale automatiquement avec la largeur du sidebar

## Fichiers modifiés
- engine/normalizer.py (nouveau)
- web/app.py (ajout endpoint)
- web/templates/index.html (ajout éléments UI)
- web/static/app.js (ajout fonctions)
- web/static/app.css (preview fluide + search bar)
