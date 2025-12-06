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

5. **Connections**

   **Implemented:**
   - Mutually confirmed: Other party must confirm for public visibility
   - Confirm/Ignore flow: Pending requests can be confirmed or ignored
   - Auto-ignore: Requests not acted on within 30 days are auto-ignored
   - Late confirmation: Ignored requests can be confirmed later
   - Re-ignore: Confirmed connections can be ignored at any time
   - Basic rate limits for spam prevention

   **Planned (future):**
   - Claims system: Separate from connections, users describe relationship in a sentence
   - Crowd-validated claims: Mutual connections can vote on claim credibility
   - Time decay: Connection strength based on claim date
   - LLM-evaluated abuse reports for automated moderation

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

### 6.2 Git Commits

Commit messages follow a consistent, concise style:

- **Lowercase**: Start with a lowercase verb
- **Imperative mood**: Use "add", "fix", "improve", not "added", "fixes", "improved"
- **Short**: Keep under ~50 characters
- **No period**: Don't end with punctuation
- **Action-focused**: Describe what the commit does, not why

**Common patterns:**

| Prefix | Usage | Examples |
|--------|-------|----------|
| `add` | New features or content | `add avatar upload`, `add video support`, `add connections` |
| `fix` | Bug fixes | `fix auth issue`, `fix voting and make top bar sticky` |
| `improve` | Enhancements to existing features | `improve esthetics`, `improve profile cover location on mobile` |
| `refactor` | Code restructuring | `refactor posts for code reuse` |
| `remove` | Deletions | `remove unnecessary video controls`, `remove download button` |
| `change` | Modifications | `change vote system`, `change comments UI` |
| `simplify` | Making things simpler | `simplify autoignore old connection requests` |
| `enable` | Turning on features | `enable edit page` |
| `update` | Updates to docs or configs | `update CLAUDE.md` |

**Examples from history:**

```
add page editors management
remove disclosure of the author of a page post
fix usability of profile on mobile
improve experience of starting post as a page
simplify message
convert emoticons to emojis in posts
```

**Avoid:**
- Past tense: ~~"added feature"~~, ~~"fixed bug"~~
- Capitalized: ~~"Add feature"~~
- Verbose: ~~"This commit adds the ability to..."~~
- Vague: ~~"update code"~~, ~~"misc changes"~~

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

- **User Profiles** (`/u/{handle}`):
  - Editable handle, name, headline, skills
  - Avatar and cover image upload (R2 storage)
  - Handle availability check with rate limiting
  - Self-service data export (JSON)
  - Self-service account deletion

- **Posts & Feed**:
  - Text posts with optional media (images/videos)
  - Reverse-chronological global feed at `/`
  - Visibility: public or connections-only
  - Scale voting system (-3 to +3) with tilting balance icon
  - Threaded comments with nested replies
  - Share posts via `/post/{post_id}` URL
  - Report abuse functionality

- **Pages** (organization profiles):
  - Page types: company, event, product, community, virtual
  - Page profile at `/p/{handle}` with icon, cover, description
  - Owner and editor roles (editors can post on behalf of page)
  - Editor invitation system with accept/decline flow
  - Ownership transfer between editors
  - Page posts appear in followers' feeds
  - **Privacy**: Page post authors are hidden from API (only page shown)
  - Follow/unfollow pages

- **Connections**:
  - Mutual confirmation required for visibility
  - Pending connections management (confirm/ignore)
  - Auto-ignore after 30 days of inactivity
  - Late confirmation of ignored requests
  - Re-ignore confirmed connections at any time

- **Messages**:
  - Real-time messaging between connected users
  - WebSocket-based notifications

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
  - `app/storage.py` - R2/S3 media storage helpers
  - `app/ratelimit.py` - Rate limiting decorator
  - `app/migrate.py` - Database migration tool
  - `app/routers/auth.py` - Auth endpoints
  - `app/routers/pages.py` - HTML page routes
  - `app/routers/api.py` - User API endpoints (profile, export, delete)
  - `app/routers/posts.py` - Posts API (CRUD, voting, comments)
  - `app/routers/page_api.py` - Pages API (CRUD, editors, follows)
  - `app/routers/messages.py` - Messaging API
  - `app/templates/` - Jinja2 templates
  - `static/js/posts.js` - Shared post rendering JavaScript

- **Frontend Architecture**:
  - Shared JavaScript in `static/js/posts.js` for consistent post rendering
  - Key shared functions: `renderPost`, `renderScaleIcon`, `renderVotePicker`, `formatPostContent`, `sharePost`
  - Templates use shared code: `index.html`, `page_profile.html`, `single_post.html`

- **Stack**:
  - Python 3.11+
  - FastAPI + Uvicorn
  - PostgreSQL + asyncpg
  - Jinja2 templates
  - Tailwind CSS (CDN)
  - Cloudflare R2 for media storage
  - Resend (transactional email)
  - bcrypt + PyJWT

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (required) |
| `JWT_SECRET` | Secret for signing tokens (required) |
| `RESEND_API_KEY` | Resend API key for emails (required) |
| `BASE_URL` | Base URL for email links (required) |
| `R2_ACCOUNT_ID` | Cloudflare R2 account ID |
| `R2_ACCESS_KEY_ID` | R2 access key |
| `R2_SECRET_ACCESS_KEY` | R2 secret key |
| `R2_BUCKET_NAME` | R2 bucket name |
| `R2_PUBLIC_URL` | Public URL for R2 bucket |

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

### Key URLs

| URL | Purpose |
|-----|---------|
| `/` | Home feed (chronological) |
| `/u/{handle}` | User profile |
| `/p/{handle}` | Page profile |
| `/post/{post_id}` | Single post view (shareable) |
| `/pages` | My pages list |
| `/p/{handle}/editors` | Manage page editors |
| `/messages` | Messages inbox |

### Next Steps

- A redesign of the voting UI. Remains -3,-2,-1,+1,+2,+3 but with a nicer UI. Balance(scales) UI is not cool.
- Claims system (separate from connections, relationship descriptions)
- Crowd-validated claims (mutual connections vote on credibility using the -3-+3 scale used for posts)
- Time decay for claim strength (from which connection strength is agreggated)
- LLM-evaluated abuse reports for automated moderation
