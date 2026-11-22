import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import agent, auth, evals, google, memory, presets, scheduler, voice
from app.core.config import APP_BASE_URL, COOKIE_SECURE, CORS_ORIGINS, JWT_SECRET_KEY
from app.db.session import verify_schema

if APP_BASE_URL.startswith(("http://localhost", "http://127.0.0.1")):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if COOKIE_SECURE and JWT_SECRET_KEY == "local-development-only-change-before-deployment":
        raise RuntimeError("Set a private JWT_SECRET_KEY before serving over HTTPS")
    verify_schema()
    yield


app = FastAPI(title="Predestination - AI Visual Scheduler", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
ROOT_DIR = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT_DIR / "frontend" / "index.html"
LANDING_PATH = ROOT_DIR / "frontend" / "landing.html"
app.mount("/assets", StaticFiles(directory=ROOT_DIR / "frontend" / "assets"), name="assets")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(INDEX_PATH)


@app.get("/home", response_class=HTMLResponse)
def home():
    return FileResponse(LANDING_PATH)


app.include_router(auth.router)
app.include_router(scheduler.router)
app.include_router(presets.router)
app.include_router(memory.router)
app.include_router(agent.router)
app.include_router(google.router)
app.include_router(evals.router)
app.include_router(voice.router)


@app.middleware("http")
async def authenticated_cache_and_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if (
        request.url.path.startswith("/api/")
        and request.method in ("POST", "PUT", "PATCH", "DELETE")
        and origin
        and origin.rstrip("/") not in CORS_ORIGINS
    ):
        return JSONResponse({"error": "Untrusted request origin"}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
