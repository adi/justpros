import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import connect, disconnect, database
from app.routers import api, auth, messages, pages, posts

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


async def auto_ignore_old_connection_requests():
    """Background task to auto-ignore connection requests older than 30 days.

    Sets receiver_deleted timestamp on requests that have been pending for 30+ days.
    This effectively 'ignores' them without any explicit action from the receiver.
    """
    while True:
        await asyncio.sleep(3600)  # Run every hour
        try:
            # Find pending requests older than 30 days and soft-delete for receiver
            # A request is pending if:
            # 1. It's a 'connection_request' kind message
            # 2. There's no 'confirm' message from receiver to sender after it
            # 3. receiver_deleted is NULL
            # 4. It's older than 30 days
            await database.execute(
                """
                UPDATE messages m
                SET receiver_deleted = NOW()
                WHERE m.kind = 'connection_request'
                  AND m.receiver_deleted IS NULL
                  AND m.created_at < NOW() - INTERVAL '30 days'
                  AND NOT EXISTS (
                      SELECT 1 FROM messages m2
                      WHERE m2.kind = 'confirm'
                        AND m2.sender_id = m.receiver_id
                        AND m2.receiver_id = m.sender_id
                        AND m2.created_at > m.created_at
                  )
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
