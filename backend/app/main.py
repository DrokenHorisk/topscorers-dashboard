from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from .core import build_all_datasets

app = FastAPI(title="TopScorers Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/dashboard", response_class=Response)
async def dashboard():
    html, _meta = build_all_datasets()
    return Response(content=html, media_type="text/html; charset=utf-8")

@app.get("/healthz")
async def healthz():
    return {"ok": True}
