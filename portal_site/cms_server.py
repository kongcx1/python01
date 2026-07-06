from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json
import os

BASE_DIR = Path(__file__).resolve().parent
CONTENT_PATH = BASE_DIR / "content.json"
ADMIN_TOKEN = os.getenv("PORTAL_ADMIN_TOKEN", "kizuna-admin")

app = FastAPI()

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)


@app.get("/api/content")
def get_content():
  if CONTENT_PATH.exists():
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
  return {}


@app.put("/api/content")
async def update_content(request: Request):
  token = request.headers.get("x-admin-token")
  if token != ADMIN_TOKEN:
    raise HTTPException(status_code=401, detail="Invalid token")
  payload = await request.json()
  CONTENT_PATH.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2),
    encoding="utf-8",
  )
  return JSONResponse({"ok": True})


@app.get("/admin")
def admin_page():
  return FileResponse(BASE_DIR / "admin.html")


app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")
