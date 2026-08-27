import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from asistencia.resolver import cerrar_dia, procesar_marcaciones_pendientes


class Command(BaseCommand):
    help = (
        "Cierra uno o varios días de asistencia: procesa las marcaciones pendientes y "
        "determina el estado final (puntual/tardanza/falta/parcial/ambiguo) de cada "
        "Asignación programada. Respeta los Feriados y Suspensiones registrados "
        "(esos días no generan ningún estado). Pensado para correr después de "
        "terminado el horario del día (o de varios días atrasados, con --desde/--hasta)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha",
            help="Cierra un solo día, en formato DD/MM/AAAA. Por defecto, hoy.",
        )
        parser.add_argument(
            "--desde",
            help="Cierra un rango de días: fecha inicial DD/MM/AAAA (usar junto con --hasta).",
        )
        parser.add_argument(
            "--hasta",
            help="Fecha final DD/MM/AAAA del rango (usar junto con --desde).",
        )

    def handle(self, *args, **options):
        if options["desde"] and options["hasta"]:
            desde = datetime.datetime.strptime(options["desde"], "%d/%m/%Y").date()
            hasta = datetime.datetime.strptime(options["hasta"], "%d/%m/%Y").date()
            fechas = []
            f = desde
            while f <= hasta:
                fechas.append(f)
                f += datetime.timedelta(days=1)
        elif options["fecha"]:
            fechas = [datetime.datetime.strptime(options["fecha"], "%d/%m/%Y").date()]
        else:
            fechas = [timezone.localdate()]

        self.stdout.write("Procesando marcaciones pendientes antes del cierre...")
        procesar_marcaciones_pendientes()

        total = {}
        for fecha in fechas:
            resumen = cerrar_dia(fecha)
            if resumen:
                self.stdout.write(f"  {fecha.strftime('%d/%m/%Y')}: {dict(resumen)}")
                for k, v in resumen.items():
                    total[k] = total.get(k, 0) + v

        if not total:
            self.stdout.write(self.style.WARNING("No hubo ninguna Asignación programada en ese rango (o todo era feriado/suspensión)."))
            return

        self.stdout.write(self.style.SUCCESS(f"Cierre completado ({len(fechas)} día(s) revisados):"))
        for clave, valor in total.items():
            self.stdout.write(f"  {clave}: {valor}")
