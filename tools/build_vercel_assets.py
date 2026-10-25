"""Copy approved public assets to Vercel's CDN directory."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]
shutil.copytree(root/'static',root/'public/static',dirs_exist_ok=True)
