#!/usr/bin/env python3
"""Root-level entry point for running the backend."""

import sys
import os
from pathlib import Path

# Ensure project root is in Python path BEFORE any imports
project_root = Path(__file__).parent.absolute()
project_root_str = str(project_root)

if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

# Set PYTHONPATH as well
os.environ["PYTHONPATH"] = project_root_str

# Change to project root directory
os.chdir(project_root_str)

# Now import and run the backend
if __name__ == "__main__":
    import uvicorn
    from backend.config import config
    
    reload_enabled = os.getenv("RELOAD", "false").lower() in ("1", "true", "yes")

    uvicorn.run(
        "backend.main:app",
        host=config.host,
        port=config.port,
        reload=reload_enabled,
        log_level=config.log_level.lower(),
    )

