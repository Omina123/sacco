import os
import sys

# Add project directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Replace 'sacco_project' with your actual Django project name (folder with settings.py)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sacco.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
