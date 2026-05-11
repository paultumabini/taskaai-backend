"""
serializers.py — DRF serializers for TaskaAI

Serializer role in DRF:
────────────────────────
  Serializers translate between complex Python objects (Django model instances)
  and primitive Python types that can be rendered to JSON (for API responses)
  or parsed from JSON (for API requests).

  Two directions:
    Serialization   (model → JSON):  serializer.data        → called in views on GET
    Deserialization (JSON → model):  serializer.is_valid()  → called in views on POST/PATCH

M2M field pattern used here (tags, assignees):
────────────────────────────────────────────────
  Django M2M fields cannot be set during object creation — the task must exist
  in the DB first (needs a PK) before the join table can have rows.

  Read fields  (tags, assignees):     use nested serializers → return full objects in GET responses
  Write fields (tag_names, assignee_ids): write_only=True → only accepted on POST/PATCH
  The create() and update() methods pop M2M fields before saving the object,
  then set them afterwards via task.tags.set(tags).

  source='assignees' on assignee_ids tells DRF the field maps to the
  'assignees' attribute on the model — so validated_data uses 'assignees' as key.

read_only_fields and the AI fields:
──────────────────────────────────────
  ai_ranked and ai_suggestion are in read_only_fields because clients should not
  be able to arbitrarily set them on every request. They are only set during task
  creation via perform_create() in views.py, which extracts them directly from
  request.data and passes them as kwargs to serializer.save(**kwargs).

  serializer.save(**kwargs) merges kwargs into validated_data AFTER validation,
  so the read_only restriction is bypassed safely and intentionally.
"""

from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Project, Tag, Task


# ── USER SERIALIZERS ──────────────────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for embedding user info in task responses.
    Only exposes safe, non-sensitive fields (no password hash).
    """
    class Meta:
        model  = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'is_staff', 'is_superuser',
        ]


class RegisterSerializer(serializers.ModelSerializer):
    """
    Write-only serializer for the POST /api/auth/register/ endpoint.

    password_confirm:
        Extra field not on the User model — used only for validation.
        write_only=True ensures it never appears in the response.

    validate():
        Cross-field validation — checks both password fields match.
        Runs after individual field validation has passed.

    create():
        Uses User.objects.create_user() instead of User.objects.create()
        because create_user() hashes the password via pbkdf2_sha256.
        Plain create() would store the password as plaintext — never do this.
    """
    password         = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model  = User
        fields = ['username', 'email', 'password', 'password_confirm', 'first_name', 'last_name']

    def validate(self, data):
        """Cross-field validation: ensure both password fields match."""
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        return data

    def create(self, validated_data):
        """
        Remove password_confirm (not a model field) then create the user
        with a properly hashed password via create_user().
        """
        validated_data.pop('password_confirm')
        return User.objects.create_user(**validated_data)


# ── PROJECT SERIALIZERS ───────────────────────────────────────────────────────

class TagSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for Tag objects — only id and name needed.
    Used as a nested serializer inside TaskSerializer's tags field.
    """
    class Meta:
        model  = Tag
        fields = ['id', 'name']


class ProjectSerializer(serializers.ModelSerializer):
    """
    Serializer for Project CRUD endpoints.

    tags: read-only nested — returns full Tag objects in GET responses.
    task_count: computed field — calls get_task_count() below.
        SerializerMethodField is read-only and calls get_<field_name>() by convention.
    """
    tags       = TagSerializer(many=True, read_only=True)
    task_count = serializers.SerializerMethodField()

    class Meta:
        model        = Project
        fields       = ['id', 'name', 'description', 'color', 'tags', 'task_count', 'created_at']
        read_only_fields = ['created_at']

    def get_task_count(self, obj):
        """Returns the number of tasks in this project. Called by SerializerMethodField."""
        return obj.tasks.count()


# ── TASK SERIALIZER ───────────────────────────────────────────────────────────

class TaskSerializer(serializers.ModelSerializer):
    """
    Full serializer for Task CRUD.

    Read fields (nested objects returned in GET):
        tags       → [{ id, name }, ...]
        assignees  → [{ id, username, email, ... }, ...]
        created_by → { id, username, ... }

    Write fields (accepted in POST/PATCH but not returned):
        tag_names    → ['frontend', 'backend'] — strings converted to Tag objects in create/update
        assignee_ids → [1, 2]                  — user PKs, source='assignees' maps to the M2M field

    Read-only fields (cannot be set by client — set server-side or by AI logic):
        created_by, ai_ranked, ai_suggestion, created_at, updated_at

    Note on ai_ranked / ai_suggestion:
        These are read_only here but ARE set during creation via perform_create()
        in views.py which passes them as kwargs to serializer.save(**kwargs).
        This is an intentional bypass — the client sends them but they're only
        accepted through the trusted server-side code path, not open validation.
    """

    # Read: full tag objects in GET responses
    tags      = TagSerializer(many=True, read_only=True)

    # Write: list of plain strings → _set_tags() converts to Tag objects
    # required=False so tasks can be created without tags
    tag_names = serializers.ListField(
        child    = serializers.CharField(max_length=50),
        write_only = True,
        required   = False,
        default    = list,   # default to empty list if not provided
    )

    # Read: full user objects in GET responses
    assignees = UserSerializer(many=True, read_only=True)

    # Write: list of user PKs, mapped to the 'assignees' M2M field via source=
    assignee_ids = serializers.PrimaryKeyRelatedField(
        queryset = User.objects.all(),
        many     = True,
        write_only = True,
        required   = False,
        source     = 'assignees',  # tells DRF the validated_data key is 'assignees'
    )

    created_by = UserSerializer(read_only=True)

    class Meta:
        model  = Task
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'due_date', 'project', 'tags', 'tag_names',
            'assignees', 'assignee_ids', 'created_by',
            'ai_ranked', 'ai_suggestion',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            # Set server-side in perform_create(), not by client validation
            'created_by', 'ai_ranked', 'ai_suggestion',
            'created_at', 'updated_at',
        ]

    def create(self, validated_data):
        """
        Create a new Task with M2M relations.

        Why pop before create:
            Django M2M relations require the parent object to exist in the DB
            (have a PK) before the join table rows can be inserted.
            If we pass M2M fields to Task.objects.create(), it raises a TypeError.
            So we pop them, create the task, then set the M2M via .set().

        tag_names → _set_tags():
            Each name is looked up or created as a Tag scoped to this project.
            task.tags.set(tags) replaces the entire M2M relation atomically.

        assignees:
            Comes in as a list of User objects (after PrimaryKeyRelatedField validates).
            task.assignees.set(assignees) sets the M2M relation.
        """
        tag_names = validated_data.pop('tag_names', [])
        assignees = validated_data.pop('assignees', [])

        task = Task.objects.create(**validated_data)

        task.assignees.set(assignees)
        self._set_tags(task, tag_names)

        return task

    def update(self, instance, validated_data):
        """
        Update an existing Task via PATCH (partial update).

        PATCH behaviour:
            DRF only includes fields that were present in the request body in
            validated_data. Fields not sent are simply not updated.

        M2M update strategy:
            tag_names and assignees are popped first (same reason as create).
            We only call .set() if the field was explicitly in the request —
            checked by whether the key was present in validated_data BEFORE pop.
            This allows: 'send tag_names=[] to clear all tags' to work correctly.

        save() with update_fields:
            Not used here because we update variable fields depending on the
            request. Full instance.save() is acceptable for PATCH with few fields.
        """
        # Pop M2M fields — None means "not in request", [] means "explicitly cleared"
        tag_names = validated_data.pop('tag_names', None)
        assignees = validated_data.pop('assignees', None)

        # Update all scalar fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Only update M2M if explicitly provided in request
        if assignees is not None:
            instance.assignees.set(assignees)
        if tag_names is not None:
            self._set_tags(instance, tag_names)

        return instance

    def _set_tags(self, task, tag_names):
        """
        Convert a list of tag name strings to Tag model instances and set the M2M.

        get_or_create(name=..., project=...):
            Atomic lookup-or-insert scoped to this project.
            Prevents duplicate tags within a project.
            Returns (tag_instance, created_bool) — we only need the instance.

        .strip() and .lower():
            Normalise tag names so 'Frontend', ' frontend', 'FRONTEND'
            all resolve to the same tag object.

        task.tags.set(tags):
            Replaces the ENTIRE M2M relation — removes old tags not in the new
            list, adds new ones. This is the correct approach for a "replace all"
            operation vs .add() which only appends.
        """
        # Track previous tags so we can clean up project-level orphan tags after re-assignment.
        previous_tag_ids = set(task.tags.values_list('id', flat=True))
        tags = []
        for name in tag_names:
            clean = name.strip().lower()
            if not clean:
                continue
            tag, _ = Tag.objects.get_or_create(
                name    = clean,
                project = task.project,
            )
            tags.append(tag)

        task.tags.set(tags)

        # Remove tags that were detached from this task and are no longer used by any task
        # in the same project. This keeps backend tag storage aligned with UI pill removals.
        current_tag_ids = set(t.id for t in tags)
        removed_tag_ids = previous_tag_ids - current_tag_ids
        if removed_tag_ids:
            Tag.objects.filter(
                id__in=removed_tag_ids,
                project=task.project,
                tasks__isnull=True,
            ).delete()


# ── UTILITY SERIALIZERS ───────────────────────────────────────────────────────

class TaskStatsSerializer(serializers.Serializer):
    """
    Read-only serializer for the /api/tasks/stats/ response.
    Uses plain Serializer (not ModelSerializer) because the data is
    aggregated in the view, not fetched directly from a single model.
    """
    total           = serializers.IntegerField()
    by_status       = serializers.DictField(child=serializers.IntegerField())
    by_priority     = serializers.DictField(child=serializers.IntegerField())
    ai_ranked       = serializers.IntegerField()
    overdue         = serializers.IntegerField()
    completion_rate = serializers.FloatField()


class AISuggestSerializer(serializers.Serializer):
    """
    Validates the request body for POST /api/tasks/suggest/.
    Simple serializer — just title (required) and description (optional).
    """
    title       = serializers.CharField(max_length=300)
    description = serializers.CharField(required=False, allow_blank=True, default='')
