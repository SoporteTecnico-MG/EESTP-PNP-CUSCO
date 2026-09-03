from django.apps import AppConfig


class AsistenciaConfig(AppConfig):
    name = 'asistencia'

    def ready(self):
        from . import signals  # noqa: F401 — conecta las señales de login/logout
