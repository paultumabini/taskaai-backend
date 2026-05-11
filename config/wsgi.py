"""
WSGI config for TaskaAI backend.

This exposes the WSGI callable used by synchronous application servers
(e.g. Gunicorn/uWSGI) in production deployments.
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
application = get_wsgi_application()
