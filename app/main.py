from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import connect, disconnect
from app.routers import api, auth, pages

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.templates = templates
    await connect()
    yield
    await disconnect()


app = FastAPI(title="JustPros", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(api.router)


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(BASE_DIR / "static" / "favicon.ico")


@app.get("/robots.txt")
async def robots():
    return FileResponse(BASE_DIR / "static" / "robots.txt")


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools():
    return {}


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")
