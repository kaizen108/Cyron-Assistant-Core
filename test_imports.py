#!/usr/bin/env python3
"""Test script to verify all imports work correctly."""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

os.environ["PYTHONPATH"] = str(project_root)
os.chdir(project_root)

print("Testing imports...")
print(f"Project root: {project_root}")
print(f"Python path includes project root: {project_root in [Path(p) for p in sys.path]}")
print()

# Test bot imports
try:
    print("Testing bot imports...")
    from bot.config import config
    print("[OK] bot.config imported successfully")
    
    from bot.cogs import setup, tickets
    print("[OK] bot.cogs imported successfully")
    
    from bot.utils.http_client import get_client
    print("[OK] bot.utils.http_client imported successfully")
    
    import discord
    print("[OK] discord imported successfully")
    
    print("\n[OK] All bot imports successful!")
except Exception as e:
    print(f"[ERROR] Bot import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test backend imports
try:
    print("\nTesting backend imports...")
    from backend.config import config as backend_config
    print("[OK] backend.config imported successfully")
    
    from backend.api import health, relay
    print("[OK] backend.api imported successfully")
    
    from backend.schemas.relay import RelayRequest, RelayResponse
    print("[OK] backend.schemas.relay imported successfully")
    
    print("\n[OK] All backend imports successful!")
except Exception as e:
    print(f"[ERROR] Backend import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*50)
print("[OK] All imports successful! Project structure is correct.")
print("="*50)

