#!/usr/bin/env python3
"""Root-level entry point for running the bot."""

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

# Now import and run the bot
from bot.main import main
import asyncio

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

