# TaskFlow

A task management API with background notifications. Users own projects, create tasks inside them, assign tasks to other users, and get notified (simulated) when a task is reassigned to them or goes overdue.

**Stack:** FastAPI · SQLAlchemy 2.0 (sync) · Alembic · PostgreSQL · Redis · Celery (worker + beat) · PyJWT · bcrypt · prometheus-client · pytest · ruff

## Setup

### Run the full stack (Docker)

Requires Docker with the compose plugin.

```bash
git clone https://github.com/floramchi/taskflow-backend.git
cd taskflow-backend
docker compose up --build
```

This starts five containers: `api`, `worker`, `beat`, `db` (Postgres) and `redis`. The `api` container applies migrations on start (`alembic upgrade head`), so there is no separate migration step.

- API: <http://localhost:8000>
- Interactive docs (with an Authorize button for the login flow): <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- Metrics: <http://localhost:8000/metrics>

`JWT_SECRET` defaults to `change-me` in compose. Set a real one for anything beyond local use:

```bash
JWT_SECRET=$(openssl rand -hex 32) docker compose up --build
```

### Try it

```bash
curl -s -X POST localhost:8000/auth/signup -H 'content-type: application/json' \
  -d '{"email":"me@example.com","password":"password123"}'

TOKEN=$(curl -s -X POST localhost:8000/auth/login \
  -d 'username=me@example.com&password=password123' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST localhost:8000/projects -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"name":"Launch"}'

curl -si localhost:8000/tasks -H "authorization: Bearer $TOKEN"   # see the X-Cache header
```

### Run locally without Docker for the app

Run only the dependencies in Docker and the app on your machine (Python 3.12+):

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
docker compose up -d db redis
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.worker.celery_app worker -B --loglevel=info   # in a second terminal
```

### Tests and lint

Tests need Postgres and Redis (`docker compose up -d db redis`). They use a separate `taskflow_test` database, created automatically, and Redis database 1, which is flushed before every test.

```bash
pytest
ruff check . && ruff format --check .
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://taskflow:taskflow@localhost:5432/taskflow` | Postgres. Plain `postgresql://` URLs are rewritten to the psycopg driver. |
| `REDIS_URL` | `redis://localhost:6379/0` | Cache and Celery broker |
| `JWT_SECRET` | `change-me` | HS256 signing key |
| `JWT_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `CACHE_TTL_SECONDS` | `60` | Lifetime of cached `GET /tasks` pages |
| `OVERDUE_SCAN_SECONDS` | `60` | How often Celery beat scans for overdue tasks |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | Run jobs inline. Tests only. |
| `TEST_DATABASE_URL`, `TEST_REDIS_URL` | local test DB / Redis db 1 | Used by the test suite |

## API overview

| Method and path | Description |
|---|---|
| `POST /auth/signup` | Create an account |
| `POST /auth/login` | OAuth2 password form, returns a bearer token |
| `GET /auth/me` | Current user |
| `POST /projects`, `GET /projects` | Create / list your projects |
| `GET/PATCH/DELETE /projects/{id}` | Read, update, delete one of your projects |
| `POST /projects/{id}/tasks` | Create a task in a project |
| `GET/PATCH/DELETE /tasks/{id}` | Read, update, delete a task |
| `GET /tasks` | List your tasks. Filters: `status`, `assignee_id`, `project_id`, `due_after`, `due_before`. Pagination: `page`, `size` (max 100). Response has `items`, `total`, `page`, `size`. |
| `GET /notifications` | Your notifications, newest first, paginated |
| `GET /health` | Checks Postgres and Redis. 200, or 503 naming the failing component. |
| `GET /metrics` | Prometheus text format |

## Architecture

```
app/
  main.py          app factory: routers, metrics middleware, error handler
  core/            config, DB session, security (bcrypt + JWT), Redis cache, metrics
  models/          SQLAlchemy models: User, Project, Task, Notification
  schemas/         Pydantic request/response models
  api/deps.py      get_db, get_current_user, ownership-checked lookups
  api/routes/      auth, projects, tasks, notifications, ops (health + metrics)
  services/        business logic; routes stay thin
  worker/          Celery app (with beat schedule) and the notification jobs
alembic/           migrations
```

Requests flow route → dependency (auth + ownership) → service → database. Anything slow or deferrable goes to Celery.

```
client ──► api ──► Postgres
            │  └─► Redis (task list cache)
            └─ .delay() after commit ─► Redis (broker) ─► worker ─► Postgres (notifications)
                                         beat ─ every N seconds ─► worker (overdue scan)
```

### Key decisions

**Authentication: stateless JWT.** The service is API-only, so signed bearer tokens avoid a server-side session store and let any API replica verify a token. The cost is that a token can't be revoked before it expires (see tradeoffs). Passwords are hashed with bcrypt, and the response schemas have no password field, so a hash can't be serialized by accident.

**Authorization: ownership on every query.** Projects have an `owner_id`. Tasks are only reachable by joining through a project the caller owns. Another user's project or task returns **404, not 403**, so ids can't be probed to learn what exists.

**Notifications run only in Celery.**
- *Reassignment:* the task service detects an assignee change and calls `notify_reassigned.delay(...)` **after** the DB commit, so the worker always sees committed data. The job re-checks that the task still has that assignee before writing, so a stale job does nothing.
- *Overdue:* a beat job runs every `OVERDUE_SCAN_SECONDS` and inserts a notification for every task that is past due, not `done`, and has an assignee. It is a single `INSERT ... SELECT`.
- *Deduplication:* a partial unique index on `(task_id, type) WHERE type = 'overdue'` plus `ON CONFLICT DO NOTHING` means repeated scans never notify twice for the same task, even if two scans overlap. Reassignment notifications are deliberately not unique, because each reassignment is a distinct event.
- *Delivery* is simulated with a row in `notifications` plus a log line.

**Caching `GET /tasks`: versioned keys.**
- Each cached page is stored under `tasks:{user_id}:v{version}:{hash of filters and pagination}`.
- Any task create, update or delete (and deleting a project, which cascades to tasks) runs `INCR tasks_ver:{user_id}`. The next read builds a key with the new version, so it can never see the old page. Orphaned entries expire through the TTL.
- This avoids `SCAN` or pattern deletes, and a status change is visible on the very next `GET /tasks`.
- The version is read before the DB query, so a write racing with a read can only leave a stale entry under a version nobody reads again.
- If Redis is down, every cache call degrades to a miss and the endpoint serves from Postgres.
- The `X-Cache: HIT|MISS` response header exists so tests (and curl) can observe the cache.

**Metrics.** Middleware counts requests and 5xx errors, labelled by method, route *template* (`/tasks/{task_id}`, not `/tasks/42`) and status. Unmatched paths share one `unmatched` label, so label cardinality stays bounded.

**Schema changes** are only applied through Alembic. The test suite builds its schema by running the real migrations, so they are tested too.

## Deployment

**Path taken: a documented, scripted deployment. It was not executed, and there is no live URL.**

- `render.yaml` is a Render Blueprint describing the web service, worker, beat, managed Postgres and Key Value (Redis). It reuses the same `Dockerfile`, with `dockerCommand` overrides for the worker and beat. The app rewrites Render's `postgresql://` connection string to the psycopg driver.
- `scripts/deploy.sh user@host` deploys to any Linux VM with Docker: it rsyncs the code, then runs `docker compose up -d --build` and polls `/health`. The server keeps its own `.env` (with `JWT_SECRET`), which the script never overwrites.

Both rely on the API container running migrations on start. That is fine for a single API instance. With several replicas, migrations should become a separate release step.

## CI

`.github/workflows/ci.yml` runs on pushes and pull requests:
- **lint:** `ruff check` and `ruff format --check`
- **test:** `pytest` against Postgres and Redis service containers

It has not been run on GitHub; the same commands pass locally.

## Assumptions

- **Visibility is scoped to the project owner.** An assignee who doesn't own the project cannot see or edit the task. They only receive notifications about it. Project sharing and members are out of scope.
- **404 instead of 403** for resources the caller doesn't own.
- **The assignee must be an existing user**, otherwise the request fails with 422. Any user can be assigned, since there are no project members.
- **Overdue notifications are sent once per task**, to the assignee. Unassigned tasks are skipped, since there is nobody to notify. If a task's due date is pushed back after the notification went out, it is not notified again.
- **Reassignment notifies the new assignee only**, and only when the assignee actually changes. Unassigning (setting `null`) notifies nobody.
- "Status changes" from the assignment are covered by the cache invalidation requirement. Notifications are created for reassignment and overdue tasks, as the requirements list them.
- Emails are case-insensitive and stored lowercased. Passwords must be 8–72 characters (bcrypt ignores everything after 72 bytes).
- Due dates are timezone-aware timestamps. "Overdue" means `due_date < now()` in the database.

## Tradeoffs & what I'd do with more time

I optimized for a small, explainable codebase that covers every requirement correctly, over a larger one that does more things shallowly.

**Known weaknesses**
- **Post-commit enqueue can lose a notification.** If the process dies, or the broker is down, between the DB commit and `.delay()`, the update stands but the notification is never created. I log the failure and move on rather than failing the request. The fix is a transactional outbox: write the notification request in the same transaction as the task change, and have a worker drain it.
- **No token revocation or refresh.** A stolen JWT works until it expires. I'd add short-lived access tokens with rotating refresh tokens and a denylist.
- **Cache invalidation can be defeated by a Redis outage.** If a version bump fails while Redis is unreachable, entries written before the outage can be served until their TTL. The TTL bounds the damage to 60 seconds by default; I judged availability of the write path more important than strict consistency during an outage.
- **Cache granularity is per user.** Any write invalidates all of that user's cached pages, including unrelated filters. That is simple and correct but wasteful for users who write often.
- **The overdue scan is one global query every N seconds.** It is fine at this scale, but it scans every past-due task each run. The due-date index helps, and a "notified" marker or partitioned scan would help more.
- **Migrations run on API startup.** Fine for one instance, a race for several.
- **Metrics are per process.** Prometheus counters live in memory in each API process. With several workers I'd use multiprocess mode or a sidecar. There is no latency histogram.
- **Sync SQLAlchemy.** It matches FastAPI's threadpool model and keeps the code simple, but async SQLAlchemy would scale better for I/O-bound load.

**With more time**
- Project members and sharing, so assignees can see their tasks, with roles.
- Rate limiting on auth endpoints and login throttling.
- Structured (JSON) logging with request ids, and tracing through to Celery jobs.
- Load test the cache, to measure the hit rate and the real win from versioned keys.
- Notification preferences, read/unread state, and a real delivery channel behind the same job.
- Cursor-based pagination for large task lists, instead of offset.
- Run the deployment path for real, and add a CD step.
