from django.apps import AppConfig

class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Users'  # must match your app folder name

    def ready(self):
        # import signals when app is ready
        import Users.signals