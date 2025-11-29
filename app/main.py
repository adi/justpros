from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="JustPros")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools():
    return {}


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return (BASE_DIR / "app" / "templates" / "index.html").read_text()
