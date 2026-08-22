import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from asistencia.resolver import cerrar_dia, procesar_marcaciones_pendientes


class Command(BaseCommand):
    help = (
        "Cierra el día de asistencia: procesa las marcaciones pendientes y determina "
        "el estado final (puntual/tardanza/falta/parcial/ambiguo) de cada Asignación "
        "programada. Pensado para correr una vez, después de terminado el horario del día."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha",
            help="Fecha a cerrar en formato DD/MM/AAAA. Por defecto, hoy.",
        )

    def handle(self, *args, **options):
        if options["fecha"]:
            fecha = datetime.datetime.strptime(options["fecha"], "%d/%m/%Y").date()
        else:
            fecha = timezone.localdate()

        self.stdout.write(f"Procesando marcaciones pendientes antes del cierre...")
        procesar_marcaciones_pendientes()

        self.stdout.write(f"Cerrando el día {fecha.strftime('%d/%m/%Y')}...")
        resumen = cerrar_dia(fecha)

        if not resumen:
            self.stdout.write(self.style.WARNING("No había ninguna Asignación programada ese día."))
            return

        self.stdout.write(self.style.SUCCESS("Cierre del día completado:"))
        for clave, valor in resumen.items():
            self.stdout.write(f"  {clave}: {valor}")
