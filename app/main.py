from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="JustPros")


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return "JustPros"
