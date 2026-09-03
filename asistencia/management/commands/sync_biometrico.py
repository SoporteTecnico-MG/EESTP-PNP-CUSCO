from django.conf import settings
from django.core.management.base import BaseCommand

from asistencia.biometrico import sincronizar_biometrico


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
        self.stdout.write(f"Conectando a {options['ip']}:{options['port']} ...")
        resultado = sincronizar_biometrico(ip=options["ip"], port=options["port"])
        if resultado["ok"]:
            self.stdout.write(self.style.SUCCESS(resultado["mensaje"]))
        else:
            self.stderr.write(self.style.ERROR(resultado["mensaje"]))
