"""MineAgent 后端入口。"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST, HOST, PORT, ensure_dirs
from .db import init_db
from .routers import meta, projects, run, canvases, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    init_db()
    print(f"\n  MineAgent 已启动 → http://127.0.0.1:{PORT}\n", flush=True)
    yield


app = FastAPI(title="MineAgent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(canvases.router)
app.include_router(run.router)
app.include_router(projects.router)
app.include_router(settings.router)
app.include_router(meta.router)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "mineagent", "host": HOST, "port": PORT}


if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str, request: Request):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def no_frontend():
        return HTMLResponse(
            "<h2>前端还没有构建</h2>"
            "<p>请在项目根目录运行 <code>start.ps1</code>，或执行：</p>"
            "<pre>cd frontend\nnpm install\nnpm run build</pre>",
            status_code=200,
        )


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False, log_level="info")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
