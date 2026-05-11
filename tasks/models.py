"""
Core data models for TaskaAI.

Project: top-level workspace grouping.
Tag: project-scoped label taxonomy.
Task: kanban item with status, priority, assignment, and AI metadata.
"""
from django.db import models
from django.contrib.auth.models import User


class Project(models.Model):
    """User-owned project bucket that contains tasks and tags."""
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#7c6af7')  # hex color
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']


class Tag(models.Model):
    """Project-scoped tag. Name uniqueness is enforced per project."""
    name = models.CharField(max_length=50)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tags')

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ('name', 'project')


class Task(models.Model):
    """Main work item shown on board columns and analytics."""
    class Status(models.TextChoices):
        BACKLOG = 'backlog', 'Backlog'
        TODO = 'todo', 'To Do'
        IN_PROGRESS = 'inprogress', 'In Progress'
        REVIEW = 'review', 'Review'
        DONE = 'done', 'Done'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'med', 'Medium'
        HIGH = 'high', 'High'

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.BACKLOG)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    due_date = models.DateField(null=True, blank=True)

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    assignees = models.ManyToManyField(User, related_name='assigned_tasks', blank=True)
    tags = models.ManyToManyField(Tag, related_name='tasks', blank=True)

    # AI fields
    ai_ranked = models.BooleanField(default=False)
    ai_suggestion = models.TextField(blank=True)  # cached AI suggestion text

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_tasks')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-created_at']
