import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import connect, disconnect, database
from app.routers import api, auth, messages, pages, people, posts

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


async def auto_ignore_old_connection_requests():
    """Background task to auto-ignore connection requests older than 30 days.

    Updates pending connection requests to 'ignored' status after 30 days.
    """
    while True:
        await asyncio.sleep(3600)  # Run every hour
        try:
            # Update pending requests older than 30 days to 'ignored'
            await database.execute(
                """
                UPDATE connections
                SET status = 'ignored', responded_at = NOW()
                WHERE status = 'pending'
                  AND requested_at < NOW() - INTERVAL '30 days'
                """
            )
        except Exception as e:
            # Log but don't crash on errors
            print(f"Auto-ignore connection requests error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.templates = templates
    await connect()
    # Start background task for auto-ignoring old connection requests
    task = asyncio.create_task(auto_ignore_old_connection_requests())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await disconnect()


app = FastAPI(title="JustPros", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(api.router)
app.include_router(messages.router)
app.include_router(people.router)
app.include_router(posts.router)


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
