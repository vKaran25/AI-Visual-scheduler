import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.api import agent, auth, evals, google, memory, presets, scheduler
from app.db.session import create_db_and_tables

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="Predestination - AI Visual Scheduler", lifespan=lifespan)
ROOT_DIR = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT_DIR / "index.html"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(INDEX_PATH)


app.include_router(auth.router)
app.include_router(scheduler.router)
app.include_router(presets.router)
app.include_router(memory.router)
app.include_router(agent.router)
app.include_router(google.router)
app.include_router(evals.router)
