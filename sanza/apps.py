from django.apps import AppConfig

class SanzaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sanza'

    def ready(self):
        import sanza.signals
