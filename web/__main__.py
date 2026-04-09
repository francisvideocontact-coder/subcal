"""
Point d'entrée : python -m subcal.web
Lance le serveur FastAPI sur http://localhost:5000
"""
import sys
from pathlib import Path

# Allow running without install
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "web.app:app",
        host="127.0.0.1",
        port=5000,
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
    )
