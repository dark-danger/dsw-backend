"""
Vercel Serverless Function entrypoint for DSW Backend API.
"""
import sys
import os
import traceback

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Initialize fallback app
app = FastAPI(title="DSW Portal API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Try loading real app
import_error = None
try:
    from app.main import app as main_app
    app = main_app
except BaseException as e:
    import_error = {
        "error": str(e),
        "error_type": type(e).__name__,
        "traceback": traceback.format_exc()
    }
    print(f"CRITICAL APP IMPORT ERROR: {import_error}")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"])
    async def catch_all_error(path: str, request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=200, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "*", "Access-Control-Allow-Headers": "*"})
        return JSONResponse(
            status_code=500,
            content={
                "status": "server_import_error",
                "message": "Failed to load backend application",
                "details": import_error
            },
            headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "*", "Access-Control-Allow-Headers": "*"}
        )

# Export for Vercel
handler = app
