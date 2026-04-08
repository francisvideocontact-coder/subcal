# SubCal

Outil de recalibrage automatique de sous-titres SRT pour la post-production vidéo.

## Installation

```bash
git clone https://github.com/studiocaillou/subcal.git
cd subcal
pip install -e .
```

## Usage

```bash
# Recalibrage simple
subcal input.srt -o output.srt --format 9:16

# Avec conversion de framerate
subcal input.srt -o output.srt --format 9:16 --source-fps 25 --target-fps 23.976

# Batch (dossier)
subcal ./srt_bruts/ -o ./srt_calibres/ --batch --formats 16:9,9:16

# Dry run (rapport sans modification)
subcal input.srt --dry-run --format 9:16

# Verbose
subcal input.srt -o output.srt --format 9:16 -v
```

## Interface web

```bash
python -m subcal.web
# → http://localhost:5000
```

## Formats supportés

| Format | CPL max | CPS max | Lignes max | Usage |
|--------|---------|---------|------------|-------|
| 16:9   | 40      | 20      | 2          | YouTube, web |
| 9:16   | 22      | 17      | 3          | Reels, TikTok, Shorts |
| 1:1    | 30      | 20      | 2          | LinkedIn, Instagram feed |
