#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path                    # ADD THIS


def main():
    """Run administrative tasks."""

    # ADD THIS BLOCK — loads .env file before Django reads settings.py
    # load_dotenv() reads the .env file in the same directory as manage.py
    # and copies every KEY=VALUE pair into os.environ so settings.py can
    # read them via os.environ.get('KEY'). Without this, .env is never read.
    from dotenv import load_dotenv          # ADD THIS
    load_dotenv(Path(__file__).resolve().parent / '.env')  # ADD THIS

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()