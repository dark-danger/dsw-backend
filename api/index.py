"""
Vercel Serverless Function entrypoint for DSW Backend API.
"""

import sys
import os

# Crucial for Vercel Serverless: ensure project root is in sys.path so 'app' is discoverable
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app.main import app

# Export app for Vercel native ASGI runtime
handler = app
