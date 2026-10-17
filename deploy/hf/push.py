"""Push this repository to a Hugging Face Docker Space (run from GitHub Actions).

Env: HF_TOKEN (write token, required), HF_SPACE (optional, default <user>/hound),
     ANTHROPIC_API_KEY (optional, stored as a Space secret).
"""
import os
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
IGNORE = shutil.ignore_patterns(".git", "node_modules", ".venv", "__pycache__", "dist", ".env", "*.rdb", ".claude")

api = HfApi(token=os.environ["HF_TOKEN"])
space = os.environ.get("HF_SPACE") or f"{api.whoami()['name']}/hound"
api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)

with tempfile.TemporaryDirectory() as tmp:
    stage = Path(tmp) / "space"
    shutil.copytree(ROOT, stage, ignore=IGNORE)
    shutil.copy(ROOT / "deploy" / "hf" / "README.md", stage / "README.md")
    api.upload_folder(folder_path=str(stage), repo_id=space, repo_type="space",
                      commit_message="Deploy from GitHub", delete_patterns=["*"])

if os.environ.get("ANTHROPIC_API_KEY", "").strip():
    api.add_space_secret(space, "ANTHROPIC_API_KEY", os.environ["ANTHROPIC_API_KEY"].strip())
api.add_space_variable(space, "HOUND_LIVE_RUNS_PER_HOUR", "10")
print(f"Deployed to https://huggingface.co/spaces/{space}")
