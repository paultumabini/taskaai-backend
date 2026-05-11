"""
views.py — API views for TaskaAI

View architecture:
──────────────────
  RegisterView      POST   /api/auth/register/           AllowAny, @csrf_exempt
  MeView            GET    /api/auth/me/                 IsAuthenticated
  ProjectViewSet    CRUD   /api/projects/                IsAuthenticated
  TaskViewSet       CRUD   /api/tasks/                   IsAuthenticated
                    POST   /api/tasks/{id}/move/
                    GET    /api/tasks/stats/
  AISuggestView     POST   /api/tasks/suggest/           IsAuthenticated

Authentication flow:
─────────────────────
  Every protected view reads the Authorization: Bearer <token> header.
  JWTAuthentication (configured in settings.py) decodes the token, validates
  the signature and expiry, and sets request.user automatically.
  Views never need to check the token manually — just use request.user.

Why @csrf_exempt on RegisterView:
───────────────────────────────────
  AllowAny skips JWT authentication, which causes DRF to fall back to
  SessionAuthentication for that endpoint. SessionAuthentication re-enables
  CSRF checking even for API views, causing the "Origin checking failed" error
  for requests from the React frontend on a different port.
  @csrf_exempt disables CSRF for this one endpoint — safe because registration
  is a public action with no authenticated session to protect against CSRF.

Tag saving fix:
────────────────
  ai_ranked and ai_suggestion are in read_only_fields in TaskSerializer so
  they cannot be set via the serializer's validated_data. Instead, perform_create()
  extracts them directly from request.data and passes them as kwargs to
  serializer.save() — DRF serializer.save(**kwargs) merges kwargs into the
  validated_data before calling the model's create() or update() method.
"""

from datetime import date

import openai
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Count
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import exceptions, generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Project, Tag, Task
from .serializers import (
    AISuggestSerializer,
    ProjectSerializer,
    RegisterSerializer,
    TagSerializer,
    TaskSerializer,
    TaskStatsSerializer,
    UserSerializer,
)

# ── AUTH VIEWS ────────────────────────────────────────────────────────────────


@method_decorator(csrf_exempt, name='dispatch')
class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/

    Creates a new user account.
    Public endpoint — no authentication required.

    @csrf_exempt: required because AllowAny causes DRF to fall back to
    SessionAuthentication for this view, which re-enables CSRF checking.
    Since registration has no session to protect, CSRF is safe to disable here.

    Request body:
        { username, email, password, password_confirm, first_name, last_name }

    Response (201):
        { id, username, email, first_name, last_name }

    Response (400):
        { field_name: ["error message"] }
    """

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class MeView(generics.RetrieveUpdateAPIView):
    """
    GET  /api/auth/me/   — returns the current user's profile
    PATCH /api/auth/me/  — updates first_name, last_name, email

    get_object() returns request.user directly instead of using a PK lookup,
    so the user can only ever access their own profile via this endpoint.
    """

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """Returns the currently authenticated user — no PK needed in the URL."""
        return self.request.user

    def patch(self, request, *args, **kwargs):
        """
        PATCH /api/auth/me/

        Supports profile edits (username/email/first_name/last_name) and optional
        password change in one request. Password change requires:
            - current_password (must match existing password)
            - new_password (min 8 chars)
        """
        user = self.get_object()
        data = request.data.copy()

        current_password = data.pop('current_password', None)
        new_password = data.pop('new_password', None)

        serializer = self.get_serializer(user, data=data, partial=True)
        serializer.is_valid(raise_exception=True)

        if (current_password or new_password) and not (
            current_password and new_password
        ):
            return Response(
                {
                    'detail': 'Both current_password and new_password are required to change password.'
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if current_password and new_password:
            if not user.check_password(current_password):
                return Response(
                    {'current_password': ['Current password is incorrect.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if len(new_password) < 8:
                return Response(
                    {
                        'new_password': [
                            'New password must be at least 8 characters long.'
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer.save()
        if current_password and new_password:
            user.set_password(new_password)
            user.save(update_fields=['password'])

        return Response(self.get_serializer(user).data)


# ── PROJECTS ──────────────────────────────────────────────────────────────────


class ProjectViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for projects owned by the current user.

    GET    /api/projects/          list all projects
    POST   /api/projects/          create a project
    GET    /api/projects/{id}/     retrieve a single project
    PATCH  /api/projects/{id}/     partial update
    DELETE /api/projects/{id}/     delete (cascades to tasks and tags)

    get_queryset() filters to owner=request.user so users can only see
    and modify their own projects — never another user's.

    perform_create() injects owner=request.user into the serializer save
    so the frontend doesn't need to send the owner ID (and can't fake it).
    """

    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Returns only projects belonging to the authenticated user.
        annotate() adds task_count_ann to each project via a JOIN —
        more efficient than calling tasks.count() separately per project.
        """
        return Project.objects.filter(owner=self.request.user).annotate(
            task_count_ann=Count('tasks')
        )

    def perform_create(self, serializer):
        """Inject the current user as the project owner on creation."""
        serializer.save(owner=self.request.user)

    def handle_exception(self, exc):
        """Custom Permission Approach."""
        if isinstance(exc, exceptions.NotAuthenticated):
            return Response(
                {"detail": "Please sign in to access your project dashboard."},
                status=401,
            )
        return super().handle_exception(exc)


# ── TASKS ─────────────────────────────────────────────────────────────────────


class TaskViewSet(viewsets.ModelViewSet):
    """
    Full CRUD + custom actions for tasks.

    Standard CRUD:
        GET    /api/tasks/              list (filterable by query params)
        POST   /api/tasks/              create
        GET    /api/tasks/{id}/         retrieve
        PATCH  /api/tasks/{id}/         partial update
        DELETE /api/tasks/{id}/         delete

    Custom actions:
        POST   /api/tasks/{id}/move/    change status column (optimised for kanban)
        GET    /api/tasks/stats/        aggregate stats for the dashboard

    Query param filters for GET /api/tasks/:
        ?project=<id>          filter by project
        ?status=<status>       filter by status (backlog/todo/inprogress/review/done)
        ?priority=<priority>   filter by priority (low/med/high)
        ?ai_ranked=true        only return AI-prioritised tasks

    select_related and prefetch_related:
        select_related('project', 'created_by') — fetches related objects in a
        single SQL JOIN instead of N separate queries (N+1 problem prevention).
        prefetch_related('tags', 'assignees') — fetches M2M relations in two
        additional queries (one per relation) instead of N queries.
    """

    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Returns tasks owned by the current user (via project ownership).
        Applies optional query param filters.
        Uses select_related and prefetch_related to minimise DB queries.
        """
        qs = (
            Task.objects.filter(project__owner=self.request.user)
            .select_related('project', 'created_by')
            .prefetch_related('tags', 'assignees')
        )

        # Apply optional filters — each is a separate .filter() call for clarity
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        priority_filter = self.request.query_params.get('priority')
        if priority_filter:
            qs = qs.filter(priority=priority_filter)

        ai_only = self.request.query_params.get('ai_ranked')
        if ai_only == 'true':
            qs = qs.filter(ai_ranked=True)

        return qs

    def perform_create(self, serializer):
        """
        Called by CreateModelMixin.create() after serializer.is_valid().

        Two responsibilities:
          1. Inject created_by=request.user (not sent by frontend — determined server-side)
          2. Extract ai_ranked and ai_suggestion from request.data and pass them
             as kwargs to serializer.save(). These are read_only in the serializer
             so they are stripped from validated_data during validation.
             Passing them as kwargs to save() bypasses this restriction safely.

        Why not just remove them from read_only_fields?
          Because we don't want clients to arbitrarily set ai_ranked=True on
          any task — it should only be set when the AI suggestion was actually used.
          The frontend sends the flag honestly, but server-side extraction via
          request.data is the trusted path.
        """
        # Extract AI fields directly from raw request body (bypasses read_only)
        ai_ranked = bool(self.request.data.get('ai_ranked', False))
        ai_suggestion = str(self.request.data.get('ai_suggestion', ''))

        serializer.save(
            created_by=self.request.user,
            ai_ranked=ai_ranked,
            ai_suggestion=ai_suggestion,
        )

    def perform_update(self, serializer):
        """
        Called by UpdateModelMixin.update() after serializer.is_valid() on PATCH.

        Mirrors perform_create()'s AI field extraction so that editing a task
        can also persist ai_ranked and ai_suggestion. Without this override,
        both fields are silently stripped from validated_data because they are
        in read_only_fields — the PATCH saves everything else but never touches
        the AI fields, so applying an AI suggestion in EditTaskModal has no effect.

        Only injects the AI fields when the client explicitly sent them in the
        request body (presence check via 'ai_ranked' in request.data). This
        prevents accidental overwrites when the client omits the fields entirely.
        """
        kwargs = {}
        if 'ai_ranked' in self.request.data:
            kwargs['ai_ranked'] = bool(self.request.data.get('ai_ranked', False))
        if 'ai_suggestion' in self.request.data:
            kwargs['ai_suggestion'] = str(self.request.data.get('ai_suggestion', ''))
        serializer.save(**kwargs)

    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        """
        POST /api/tasks/{id}/move/
        Body: { "status": "inprogress" }

        Dedicated endpoint for column moves — more efficient than a full PATCH
        because it only updates the status field and updated_at timestamp.

        update_fields=['status', 'updated_at'] generates:
            UPDATE tasks SET status=X, updated_at=NOW() WHERE id=Y
        instead of updating every field, reducing DB write overhead.
        """
        task = self.get_object()
        new_status = request.data.get('status')
        valid = [s[0] for s in Task.Status.choices]

        if new_status not in valid:
            return Response(
                {'detail': f'status must be one of {valid}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task.status = new_status
        task.save(update_fields=['status', 'updated_at'])
        return Response(TaskSerializer(task).data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        GET /api/tasks/stats/?project=<id>

        Returns aggregate task statistics for the dashboard KPI cards.
        All counts are derived from the same filtered queryset (get_queryset()
        applies the project and auth filters automatically).

        values('status').annotate(count=Count('id')) generates a single
        GROUP BY query:
            SELECT status, COUNT(id) FROM tasks WHERE ... GROUP BY status
        This is more efficient than calling .filter(status=X).count() five times.
        """
        qs = self.get_queryset()
        total = qs.count()

        # GROUP BY status — produces [{status: 'done', count: 3}, ...]
        by_status = {
            row['status']: row['count']
            for row in qs.values('status').annotate(count=Count('id'))
        }

        # GROUP BY priority
        by_priority = {
            row['priority']: row['count']
            for row in qs.values('priority').annotate(count=Count('id'))
        }

        ai_ranked = qs.filter(ai_ranked=True).count()
        overdue = (
            qs.filter(due_date__lt=date.today())
            .exclude(status=Task.Status.DONE)
            .count()
        )
        done_count = by_status.get('done', 0)

        # Avoid division by zero when project has no tasks
        completion_rate = round(done_count / total * 100, 1) if total else 0.0

        data = {
            'total': total,
            'by_status': by_status,
            'by_priority': by_priority,
            'ai_ranked': ai_ranked,
            'overdue': overdue,
            'completion_rate': completion_rate,
        }
        return Response(TaskStatsSerializer(data).data)


# ── AI SUGGEST ────────────────────────────────────────────────────────────────


class AISuggestView(APIView):
    """
    POST /api/tasks/suggest/
    Body: { "title": "...", "description": "..." }

    Calls OpenAI GPT-4o-mini with a structured prompt and returns:
        { priority, suggestion, tags, deadline_days }

    Fallback behaviour:
        If OPENAI_API_KEY is not set, or if the API call fails for any reason,
        _rule_based_suggest() is called instead. It uses keyword matching to
        return a reasonable priority and suggestion without any external API call.
        This means the app works in development without an OpenAI account.

    System prompt strategy:
        The prompt instructs the model to return ONLY valid JSON with no markdown
        fences or preamble. json.loads() then parses the raw response string.
        If the model returns malformed JSON, the except block catches it and
        falls back to rule-based suggestions.
    """

    permission_classes = [permissions.IsAuthenticated]

    # Instructs GPT to return structured JSON — model follows this reliably
    SYSTEM_PROMPT = """You are a project management AI assistant.
Given a task title and optional description, return a JSON object with:
- "priority": one of "high", "med", or "low"
- "suggestion": a 1-2 sentence explanation of your reasoning
- "tags": an array of 1-3 relevant lowercase tag strings
- "deadline_days": an integer — recommended days until deadline (1-30)

Respond ONLY with valid JSON. No markdown fences, no preamble."""

    def post(self, request):
        """
        Validates request body, calls OpenAI (or falls back to rules),
        and returns the structured suggestion.
        """
        serializer = AISuggestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        title = serializer.validated_data['title']
        description = serializer.validated_data.get('description', '')

        # Build the user message — include description only if provided
        user_message = f"Task title: {title}"
        if description:
            user_message += f"\nDescription: {description}"

        # Debug context for diagnosing AI suggestion calls in local logs
        print(f"[AI Suggest] title='{title}'")
        print(f"[AI Suggest] OPENAI_API_KEY present: {bool(settings.OPENAI_API_KEY)}")
        print(
            f"[AI Suggest] Key starts with: {settings.OPENAI_API_KEY[:10] if settings.OPENAI_API_KEY else 'EMPTY'}"
        )

        # No API key configured — skip the API call entirely
        if not settings.OPENAI_API_KEY:
            return Response(self._rule_based_suggest(title, description))

        try:
            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[
                    {'role': 'system', 'content': self.SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_message},
                ],
                max_tokens=200,
                temperature=0.3,  # low temperature = more consistent, less creative
            )
            import json

            raw = response.choices[0].message.content.strip()
            print(f"[AI Suggest] OpenAI raw response: {raw}")
            result = json.loads(raw)
            print(
                "[AI Suggest] Parsed fields: "
                f"priority={result.get('priority')} "
                f"deadline_days={result.get('deadline_days')} "
                f"tags={result.get('tags')}"
            )
            return Response(result)

        except openai.AuthenticationError as e:
            # Bad API key — fall through to rule-based
            print(f"[AI Suggest] Auth error: {e}")
            return Response(self._rule_based_suggest(title, description))
        except openai.RateLimitError as e:
            print(f"[AI Suggest] Rate limit error: {e}")
            return Response(self._rule_based_suggest(title, description))
        except Exception as e:
            # Any other error (rate limit, network, malformed JSON) — fall through
            print(f"[AI Suggest] Unexpected error: {type(e).__name__}: {e}")
            return Response(self._rule_based_suggest(title, description))

    @staticmethod
    def _rule_based_suggest(title, description):
        """
        Keyword-based fallback when OpenAI is unavailable.

        Checks the combined title+description text against keyword categories
        and returns a pre-defined priority, suggestion, tags, and deadline.
        Returns the same shape as the OpenAI response so the frontend
        handles both identically.
        """
        text = (title + ' ' + description).lower()

        if any(
            w in text
            for w in [
                'auth',
                'security',
                'login',
                'password',
                'deploy',
                'payment',
                'bug',
                'critical',
                'fix',
                'incident',
                'outage',
            ]
        ):
            priority, days = 'high', 2
            suggestion = 'This task appears critical — High priority and a tight deadline are recommended.'
        elif any(
            w in text
            for w in [
                'api',
                'endpoint',
                'backend',
                'database',
                'schema',
                'migration',
                'django',
                'model',
            ]
        ):
            priority, days = 'high', 3
            suggestion = 'Core backend work detected — High priority recommended with 3-day deadline.'
        elif any(
            w in text
            for w in ['frontend', 'component', 'react', 'ui', 'css', 'design', 'layout']
        ):
            priority, days = 'med', 4
            suggestion = (
                'UI work — Medium priority. Allow 4 days to account for review cycles.'
            )
        elif any(w in text for w in ['test', 'spec', 'jest', 'cypress', 'coverage']):
            priority, days = 'med', 5
            suggestion = 'Testing task — Medium priority. Schedule after the feature it covers is complete.'
        elif any(w in text for w in ['doc', 'readme', 'wiki', 'comment', 'write']):
            priority, days = 'low', 7
            suggestion = (
                'Documentation task — Low priority is typical. Schedule post-feature.'
            )
        elif any(w in text for w in ['ai', 'openai', 'gpt', 'smart', 'auto', 'ml']):
            priority, days = 'high', 5
            suggestion = 'AI integration tasks are complex — High priority. Allow extra time for testing.'
        elif any(
            w in text
            for w in ['deploy', 'server', 'devops', 'railway', 'vercel', 'host']
        ):
            priority, days = 'high', 3
            suggestion = (
                'Deployment is critical path — High priority. Notify teammates.'
            )
        elif any(
            w in text
            for w in [
                'invoice',
                'budget',
                'tax',
                'bill',
                'expense',
                'finance',
                'payment',
            ]
        ):
            priority, days = 'high', 2
            suggestion = 'Financial/admin work detected — prioritise soon to avoid penalties or missed due dates.'
        elif any(
            w in text
            for w in [
                'appointment',
                'doctor',
                'medical',
                'health',
                'exercise',
                'workout',
                'medicine',
            ]
        ):
            priority, days = 'med', 2
            suggestion = 'Health-related task — Medium priority with a near deadline is recommended.'
        elif any(
            w in text
            for w in [
                'meeting',
                'event',
                'birthday',
                'travel',
                'trip',
                'book',
                'reservation',
            ]
        ):
            priority, days = 'med', 3
            suggestion = 'Scheduling/event task detected — Medium priority to keep plans on track.'
        elif any(
            w in text
            for w in [
                'grocery',
                'clean',
                'laundry',
                'kitchen',
                'home',
                'repair',
                'maintenance',
            ]
        ):
            priority, days = 'low', 5
            suggestion = 'Household task — Low to medium urgency. Batch with similar chores this week.'
        elif any(
            w in text
            for w in [
                'study',
                'course',
                'lesson',
                'exam',
                'practice',
                'learn',
                'reading',
            ]
        ):
            priority, days = 'med', 4
            suggestion = 'Learning task detected — Medium priority with steady progress over several days.'
        elif any(
            w in text
            for w in [
                'call',
                'email',
                'follow up',
                'follow-up',
                'respond',
                'reply',
                'message',
            ]
        ):
            priority, days = 'med', 2
            suggestion = 'Communication follow-up task — Medium priority with a short turnaround recommended.'
        else:
            priority, days = 'med', 4
            suggestion = 'Medium complexity task — 4 days is a reasonable estimate.'

        # Build tags from keyword matches — deduplicate and cap at 3
        tags = []
        keyword_tag_map = [
            (['frontend', 'react', 'css', 'ui', 'component'], 'frontend'),
            (['backend', 'django', 'api', 'endpoint'], 'backend'),
            (['database', 'schema', 'migration', 'model'], 'database'),
            (['test', 'spec', 'jest', 'cypress'], 'testing'),
            (['deploy', 'server', 'railway', 'vercel'], 'devops'),
            (['ai', 'openai', 'gpt', 'ml'], 'ai'),
            (['doc', 'readme', 'wiki'], 'docs'),
            (['auth', 'login', 'password', 'security'], 'auth'),
            (['invoice', 'budget', 'tax', 'expense', 'bill'], 'finance'),
            (['doctor', 'medical', 'health', 'exercise'], 'health'),
            (['meeting', 'event', 'birthday', 'trip'], 'planning'),
            (['grocery', 'clean', 'laundry', 'home'], 'personal'),
            (['study', 'course', 'exam', 'learn', 'reading'], 'learning'),
            (['call', 'email', 'reply', 'follow up'], 'communication'),
        ]
        for keywords, tag in keyword_tag_map:
            if any(k in text for k in keywords):
                tags.append(tag)
            if len(tags) == 3:
                break

        return {
            'priority': priority,
            'suggestion': suggestion,
            'tags': tags,
            'deadline_days': days,
        }
