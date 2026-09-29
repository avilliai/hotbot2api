"""
HotBot -> OpenAI-compatible API Proxy Server
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.routers import admin, chat
from app.routers import model_list as models
from app.cookie_manager import cm
from app.config import PORT, PROXY_API_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

_PUBLIC_PATHS = {"/", "/health", "/admin/tokens/detail"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "Missing Authorization header", "type": "auth_error"}},
            )
        token = auth_header[len("Bearer "):]
        if PROXY_API_KEY and token != PROXY_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "Invalid API key", "type": "auth_error"}},
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cm.load()
    logging.getLogger("hotbot_proxy").info(
        f"Loaded {len(cm.accounts)} HotBot accounts, active pool size: {len(cm.active_pool)}"
    )
    asyncio.create_task(cm.replenish_active_pool())
    yield


app = FastAPI(title="HotBot.com -> OpenAI Proxy", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

app.include_router(chat.router)
app.include_router(models.router)
app.include_router(admin.router)


@app.get("/")
async def serve_dashboard():
    html_path = Path("dashboard.html")
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse(
        "<h1>HotBot Chat Proxy</h1>"
        "<p>OpenAI-compatible proxy for HotBot.com</p>"
        "<ul>"
        "<li>POST /v1/chat/completions</li>"
        "<li>GET /v1/models</li>"
        "<li>GET /admin/tokens/detail</li>"
        "<li>POST /admin/register/start</li>"
        "</ul>"
    )


@app.get("/health")
async def health():
    eligible = sum(1 for a in cm.accounts if cm._account_is_eligible(a))
    return {
        "status": "ok",
        "service": "hotbot2api",
        "total_accounts": len(cm.accounts),
        "available_accounts": eligible,
        "active_pool_size": len(cm.active_pool),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
