# TaskaAI — Backend

**Live app:** [https://taskaai.vercel.app/](https://taskaai.vercel.app/)

**Demo login:** username `testuser`, password `testuser123`

Django REST API powering the TaskaAI kanban board with AI-driven task prioritization.

## Tech Stack

- **Django 4.2** + **Django REST Framework**
- **PostgreSQL** — relational data (users, projects, tasks, tags)
- **JWT auth** via `djangorestframework-simplejwt`
- **OpenAI GPT-4o-mini** — priority scoring & deadline suggestions
- **CORS** via `django-cors-headers`

---

## Project Structure

```
taskaai_backend/
├── config/
│   ├── settings.py       # All Django settings
│   └── urls.py           # Root URL conf
├── tasks/
│   ├── models.py         # Task, Project, Tag
│   ├── serializers.py    # DRF serializers
│   ├── views.py          # ViewSets + AI suggest view
│   └── urls.py           # API routes
├── requirements.txt
└── .env.example
```

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/yourname/taskaai-backend.git
cd taskaai-backend

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — add DB credentials and your OPENAI_API_KEY
```

### 3. Set up PostgreSQL

```bash
 createdb -U postgres taskaai

```

### 4. Run migrations

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Start the server

```bash
python manage.py runserver
# API available at http://localhost:8000/api/
```

---

## API Reference

### Authentication

| Method    | Endpoint              | Description          |
| --------- | --------------------- | -------------------- |
| POST      | `/api/auth/register/` | Create account       |
| POST      | `/api/auth/login/`    | Get JWT tokens       |
| POST      | `/api/auth/refresh/`  | Refresh access token |
| GET/PATCH | `/api/auth/me/`       | Current user profile |

**Login response:**

```json
{ "access": "eyJ...", "refresh": "eyJ..." }
```

Add `Authorization: Bearer <access>` to all subsequent requests.

---

### Projects

| Method | Endpoint              | Description        |
| ------ | --------------------- | ------------------ |
| GET    | `/api/projects/`      | List your projects |
| POST   | `/api/projects/`      | Create project     |
| GET    | `/api/projects/{id}/` | Get project        |
| PATCH  | `/api/projects/{id}/` | Update project     |
| DELETE | `/api/projects/{id}/` | Delete project     |

**Create project body:**

```json
{ "name": "Portfolio App", "description": "...", "color": "#7c6af7" }
```

---

### Tasks

| Method | Endpoint                | Description     |
| ------ | ----------------------- | --------------- |
| GET    | `/api/tasks/`           | List tasks      |
| POST   | `/api/tasks/`           | Create task     |
| GET    | `/api/tasks/{id}/`      | Get task        |
| PATCH  | `/api/tasks/{id}/`      | Update task     |
| DELETE | `/api/tasks/{id}/`      | Delete task     |
| POST   | `/api/tasks/{id}/move/` | Move to column  |
| GET    | `/api/tasks/stats/`     | Dashboard stats |

**List filters** (query params):

- `?project=1` — filter by project
- `?status=inprogress` — filter by status (`backlog`, `todo`, `inprogress`, `review`, `done`)
- `?priority=high` — filter by priority (`low`, `med`, `high`)
- `?ai_ranked=true` — only AI-prioritised tasks

**Create task body:**

```json
{
  "title": "Build login page",
  "description": "React form with JWT flow",
  "status": "todo",
  "priority": "high",
  "due_date": "2025-05-01",
  "project": 1,
  "tag_names": ["frontend", "auth"],
  "assignee_ids": [1]
}
```

**Move task body:**

```json
{ "status": "inprogress" }
```

**Stats response:**

```json
{
  "total": 12,
  "by_status": {
    "backlog": 2,
    "todo": 2,
    "inprogress": 5,
    "review": 1,
    "done": 2
  },
  "by_priority": { "high": 5, "med": 4, "low": 3 },
  "ai_ranked": 3,
  "overdue": 1,
  "completion_rate": 16.7
}
```

---

### AI Suggest

| Method | Endpoint              | Description                |
| ------ | --------------------- | -------------------------- |
| POST   | `/api/tasks/suggest/` | Get AI priority suggestion |

**Request body:**

```json
{
  "title": "Implement JWT refresh logic",
  "description": "Auto-renew tokens on 401"
}
```

**Response:**

```json
{
  "priority": "high",
  "suggestion": "Authentication tasks are critical path. High priority with a 2-day deadline recommended.",
  "tags": ["backend", "auth"],
  "deadline_days": 2
}
```

> Falls back to rule-based suggestions if `OPENAI_API_KEY` is not set — no crashes.

---

## Data Models

```
User (Django built-in)
 └── Project (owner FK)
      ├── Tag (project FK)
      └── Task (project FK)
           ├── tags (M2M → Tag)
           └── assignees (M2M → User)
```

**Task fields of note:**

- `ai_ranked` — bool, set to `true` after AI suggest is applied
- `ai_suggestion` — cached suggestion text
- `ai_priority_score` — float 0.0–1.0, used for ordering

---

## Deployment (Railway)

```bash
# Procfile
web: gunicorn config.wsgi --workers 2 --bind 0.0.0.0:$PORT

# Set env vars in Railway dashboard:
# SECRET_KEY, DEBUG=False, DB_*, OPENAI_API_KEY, CORS_ALLOWED_ORIGINS, ALLOWED_HOSTS
```

Run migrations on deploy:

```bash
python manage.py migrate && python manage.py collectstatic --noinput
```

---

## Connecting the React Frontend

Use the frontend service client directly from:

`taskaai_frontend/src/services/api.js`

```js
import { tasksAPI, aiAPI, authAPI } from './services/api';

// Login
await authAPI.login('jordan', 'password123');

// Fetch board tasks for a project
const tasks = await tasksAPI.list({ project: 1 });

// Get AI suggestion while user types
const suggestion = await aiAPI.suggest({ title: inputValue });

// Move a card to the next column
await tasksAPI.move(taskId, 'inprogress');

// Dashboard stats
const stats = await tasksAPI.stats(projectId);
```
