"""
Admin registrations for TaskaAI domain models.

Keeps essential list/search/filter controls close to model declarations so
admin users can quickly inspect projects, tags, and tasks.
"""
from django.contrib import admin

from .models import Project, Tag, Task


# Admin classes define table columns and filters shown in Django admin lists.
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'created_at')
    search_fields = ('name', 'owner__username')


class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'project')
    list_filter = ('project',)


class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'priority', 'project', 'ai_ranked')
    list_filter = ('status', 'priority', 'project', 'ai_ranked')
    search_fields = ('title', 'description')


# Register model/admin pairs with the site registry.
admin.site.register(Project, ProjectAdmin)
admin.site.register(Tag, TagAdmin)
admin.site.register(Task, TaskAdmin)
