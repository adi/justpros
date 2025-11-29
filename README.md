# JustPros

A clean, chronological professional network. No algorithmic nonsense.

## Stack

- **Python** + **FastAPI**
- **HTMX** + **Tailwind CSS**
- **PostgreSQL** + `databases[asyncpg]`
- **Resend** for transactional email
- **JWT** for stateless auth

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Set environment variables

```bash
export DATABASE_URL="postgresql://localhost/justpros"
export JWT_SECRET="your-secret-key"
export RESEND_API_KEY="re_..."
export BASE_URL="http://localhost:8000"
```

### 3. Create database and run migrations

```bash
createdb justpros
uv run python -m app.migrate
```

### 4. Run

```bash
uv run uvicorn app.main:app --reload
```

## Deploy

Deployed via GitHub Actions on tag push:

```bash
git tag v0.x.x && git push origin v0.x.x
```

## Project Structure

```
app/
├── main.py          # FastAPI app, lifespan, routes
├── db.py            # Database connection
├── auth.py          # JWT, password hashing, auth helpers
├── email.py         # Resend email sending
├── ratelimit.py     # Rate limiting decorator
├── routers/
│   ├── auth.py      # /auth/* endpoints
│   └── pages.py     # Page routes (signup, login, etc.)
└── templates/       # Jinja2 templates
```

## License

Source available. See [LICENSE](LICENSE) for details.

You may view and learn from this code, but deployment requires explicit permission.
