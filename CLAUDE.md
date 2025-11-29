# CLAUDE.md — JustPros Assistant Guide

Welcome 👋  
This document tells you (the AI assistant) how to work with this repo and what this project is about.

---

## 1. Project Overview

**Name:** JustPros (`justpros.org`)  
**Goal:** A clean, open, no-bullshit professional network for leaders, builders, creatives, and doers.

JustPros is an intentional alternative to LinkedIn and similar platforms. It focuses on real people, real work, and simple, honest interactions.

---

## 2. Product Vision

**Tagline idea:**  
> JustPros — the clean professional network.

**Core value props:**

- A place to **show your work**, not push corporate fluff.
- A calm, minimal interface that **respects attention**.
- An **open, community-friendly** platform (open source from day one).

**Target users:**

- Builders (engineers, founders, indie hackers)
- Creatives (designers, writers, makers)
- Leaders and operators
- Anyone who cares about craft, not corporate theater

---

## 3. Product Principles

When proposing features, writing copy, or suggesting UX changes, optimize for these:

1. **No corporate spam**  
   - No mass cold outreach tools.
   - No “growth hacking” features just for vanity metrics.

2. **No algorithmic nonsense**  
   - Default feed is **strictly chronological**.
   - No opaque ranking, no engagement bait optimization.

3. **No engagement traps**  
   - No streaks, dopamine loops, or dark patterns.
   - Features should help users do meaningful work, not “keep them scrolling.”

4. **Clean, chronological feed**  
   - Simple, mobile-first UI.
   - Posts sorted by time. Any deviation must be explicit, visible, and user-controlled.

5. **Focused on skills + work**  
   - Profiles emphasize skills, projects, outputs.
   - De-emphasize titles, status markers, “thought leadership” fluff.

When in doubt, ask:  
> “Does this make it easier for pros to show their work and connect, without bullshit?”

If not, don’t recommend it.

---

## 4. Technical Vision

**Stack (minimalist & accessible):**

- **Language:** Python
- **Framework:** FastAPI
- **Frontend:** HTMX + server-side rendered templates
- **Styling:** Tailwind CSS
- **Design:** Mobile-first

Hosting notes:

- Hosted on a personal server behind **Cloudflare**.
- Keep resource usage reasonable and deployment simple.

When suggesting code, prefer:

- Simple, readable Python
- Thin abstractions
- No unnecessary dependencies

---

## 5. Core Features (MVP Direction)

When helping design or modify features, prioritize:

1. **Auth & Profiles**
   - Email-based signup/login is enough.
   - Public profile with:
     - Name
     - One-line headline
     - Skills (tags)
     - Optional avatar
   - Public profile URL, e.g. `/u/{handle}`.

2. **Posts & Feed**
   - Text-focused posts (links optional).
   - Reverse-chronological global feed.
   - User profile feed = posts by that user.
   - Simple interactions: like/react is optional; comments are nice but can be minimal.

3. **Discovery**
   - Basic search by name and skills.
   - No complex recommendation systems in early versions.

4. **Openness**
   - Clear, simple README explaining how to run locally.
   - Code structured so others can reasonably contribute.

If a requested feature conflicts with the principles (e.g. growth-hacky engagement tricks), highlight the conflict and propose a simpler, more principled alternative.

---

## 6. Code & Architecture Guidelines

When writing or editing code, follow these preferences:

### 6.1 FastAPI

- Use **type hints** everywhere.
- Organize endpoints into routers by domain (`auth`, `profiles`, `posts`, etc.).
- Use Pydantic models for request/response schemas.
- Prefer dependency injection for auth/user context.

Example style:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/profiles", tags=["profiles"])

class ProfileUpdate(BaseModel):
    headline: str | None = None
    skills: list[str] = []

@router.post("/me")
async def update_my_profile(
    payload: ProfileUpdate,
    current_user = Depends(get_current_user),
):
    ...
```

---

## 7. Current State

### What's Done

- **Deployment pipeline**: GitHub Actions deploys on tag push (`v*`), runs migrations automatically

- **Database**:
  - PostgreSQL with `databases[asyncpg]`
  - Migration system: `migrations/` directory with numbered SQL files
  - Run migrations: `uv run python -m app.migrate`

- **Authentication**:
  - Email-based signup with verification (via Resend)
  - JWT tokens (stateless, 7-day expiry)
  - Password reset flow
  - bcrypt password hashing (72-byte limit enforced)

- **User Profiles**:
  - Editable handle, name, headline, skills
  - Handle availability check with rate limiting
  - Self-service data export (JSON)
  - Self-service account deletion

- **Rate Limiting**:
  - Custom decorator-based rate limiter
  - IP blocking after 3 violations (1 hour)
  - CF-Connecting-IP header support

- **Legal**:
  - Privacy policy (`/privacy`)
  - Terms of service (`/terms`)
  - Source-available license (deployment requires permission)

- **App Structure**:
  - `app/main.py` - FastAPI app with lifespan events
  - `app/db.py` - Database connection
  - `app/auth.py` - JWT, password hashing, auth helpers
  - `app/email.py` - Resend email sending
  - `app/ratelimit.py` - Rate limiting decorator
  - `app/migrate.py` - Database migration tool
  - `app/routers/auth.py` - Auth endpoints
  - `app/routers/pages.py` - Page routes
  - `app/routers/api.py` - API endpoints (profile, export, delete)
  - `app/templates/` - Jinja2 templates

- **Stack**:
  - Python 3.11+
  - FastAPI + Uvicorn
  - PostgreSQL + asyncpg
  - Jinja2 templates
  - HTMX 2.0.8 (CDN)
  - Tailwind CSS (CDN)
  - Resend (transactional email)
  - bcrypt + PyJWT

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (required) |
| `JWT_SECRET` | Secret for signing tokens (required) |
| `RESEND_API_KEY` | Resend API key for emails (required) |
| `BASE_URL` | Base URL for email links (required) |

### GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `DEPLOY_HOST` | Server IP |
| `DEPLOY_USER` | Deploying user |
| `DEPLOY_KEY`  | SSH private key for deployment |

### Deploy Command

```bash
git tag v0.x.x && git push origin v0.x.x
```

### Next Steps

- Public profile pages (`/u/{handle}`)
- Posts & chronological feed
- Basic search by name and skills
