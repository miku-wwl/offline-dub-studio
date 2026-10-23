import os
import tempfile
from pathlib import Path


_root = Path(tempfile.gettempdir()) / "offline-dub-studio-pytest"
os.environ.setdefault("DATA_DIR", str(_root / "data"))
os.environ.setdefault("MODELS_DIR", str(_root / "models"))
