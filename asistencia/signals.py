from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import registrar_actividad


@receiver(user_logged_in)
def _log_login(sender, request, user, **kwargs):
    registrar_actividad(request, "Inicio de sesión")


@receiver(user_logged_out)
def _log_logout(sender, request, user, **kwargs):
    registrar_actividad(request, "Cierre de sesión")


@receiver(user_login_failed)
def _log_login_failed(sender, credentials, request=None, **kwargs):
    usuario = credentials.get("username", "?")
    registrar_actividad(request, "Intento de inicio de sesión fallido", detalle=f"usuario: {usuario}")
