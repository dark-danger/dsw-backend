from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="DSW Portal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "online", "service": "DSW Geeta University Portal API", "docs": "/docs"}

@app.get("/api/health")
def read_health():
    return {"status": "healthy"}

@app.get("/health")
def read_health_root():
    return {"status": "healthy"}

@app.post("/api/auth/login")
async def dummy_login(request: Request):
    try:
        body = await request.json()
        email = body.get("email", "")
        # Real authentication logic will connect here
        return {
            "access_token": "demo-token-12345",
            "refresh_token": "demo-refresh-token-12345",
            "token_type": "bearer",
            "user": {
                "id": 1,
                "name": "Admin Yash",
                "email": email or "admin@geeta.edu.in",
                "role": "super_admin",
                "is_active": True,
                "must_change_password": False,
                "created_at": "2026-09-12T00:00:00Z"
            }
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
