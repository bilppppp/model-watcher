"""Convenience top-level entrypoint for Model Watcher."""
import sys
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from model_watcher.cli import main

if __name__ == "__main__":
    main()
