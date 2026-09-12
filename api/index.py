"""
Vercel Serverless Function entrypoint for DSW Backend API with auto error-catcher.
"""
import sys
import os
import traceback

# Ensure root directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from app.main import app as main_app
except Exception as e:
    err_tb = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    
    main_app = FastAPI()
    main_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @main_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"])
    async def catch_all(path: str):
        return JSONResponse(
            status_code=200,
            content={
                "status": "startup_import_error",
                "error": str(e),
                "traceback": err_tb
            }
        )

app = main_app
handler = main_app
