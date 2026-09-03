"""Conexión con el equipo biométrico ZKTeco iClock880 — usada tanto por el
comando de consola (sync_biometrico) como por el botón "Sincronizar" del panel."""

from django.conf import settings
from django.utils import timezone
from zk import ZK
from zk.exception import ZKErrorConnection, ZKErrorResponse

from .models import MarcacionBiometrica


def sincronizar_biometrico(ip=None, port=None):
    """Se conecta al equipo, trae las marcaciones y las guarda sin duplicar.
    Devuelve un dict: {ok, mensaje, nuevas, total}."""
    ip = ip or settings.BIOMETRICO_IP
    port = port or settings.BIOMETRICO_PORT

    zk = ZK(ip, port=port, timeout=15)
    try:
        conn = zk.connect()
    except (ZKErrorConnection, ZKErrorResponse) as exc:
        return {"ok": False, "mensaje": f"No se pudo conectar al equipo ({ip}:{port}): {exc}"}

    try:
        registros = conn.get_attendance()
    finally:
        conn.disconnect()

    nuevos = [
        MarcacionBiometrica(
            id_biometrico=str(r.user_id),
            timestamp=timezone.make_aware(r.timestamp) if timezone.is_naive(r.timestamp) else r.timestamp,
            origen_dispositivo="iClock880",
        )
        for r in registros
    ]

    antes = MarcacionBiometrica.objects.count()
    MarcacionBiometrica.objects.bulk_create(nuevos, batch_size=500, ignore_conflicts=True)
    despues = MarcacionBiometrica.objects.count()
    nuevas = despues - antes

    return {
        "ok": True,
        "mensaje": f"Sincronización completada. Marcaciones nuevas: {nuevas}. Total en base de datos: {despues}.",
        "nuevas": nuevas,
        "total": despues,
    }
