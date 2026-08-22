from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from zk import ZK
from zk.exception import ZKErrorConnection, ZKErrorResponse

from asistencia.models import MarcacionBiometrica


class Command(BaseCommand):
    help = (
        "Se conecta al equipo biométrico ZKTeco iClock880 y trae las marcaciones "
        "nuevas hacia la tabla MarcacionBiometrica, sin duplicar registros ya importados."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--ip",
            default=settings.BIOMETRICO_IP,
            help="IP del equipo biométrico (por defecto, BIOMETRICO_IP del .env).",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=settings.BIOMETRICO_PORT,
            help="Puerto del equipo biométrico (por defecto, BIOMETRICO_PORT del .env).",
        )

    def handle(self, *args, **options):
        ip = options["ip"]
        port = options["port"]

        zk = ZK(ip, port=port, timeout=15)
        self.stdout.write(f"Conectando a {ip}:{port} ...")

        try:
            conn = zk.connect()
        except (ZKErrorConnection, ZKErrorResponse) as exc:
            self.stderr.write(self.style.ERROR(f"No se pudo conectar al equipo: {exc}"))
            return

        try:
            registros = conn.get_attendance()
        finally:
            conn.disconnect()

        self.stdout.write(f"El equipo reporta {len(registros)} marcaciones en total.")

        nuevos = [
            MarcacionBiometrica(
                id_biometrico=str(r.user_id),
                timestamp=timezone.make_aware(r.timestamp)
                if timezone.is_naive(r.timestamp)
                else r.timestamp,
                origen_dispositivo="iClock880",
            )
            for r in registros
        ]

        antes = MarcacionBiometrica.objects.count()
        MarcacionBiometrica.objects.bulk_create(
            nuevos,
            batch_size=500,
            ignore_conflicts=True,
        )
        despues = MarcacionBiometrica.objects.count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Sincronización completada. Marcaciones nuevas insertadas: {despues - antes}. "
                f"Total acumulado en base de datos: {despues}."
            )
        )
