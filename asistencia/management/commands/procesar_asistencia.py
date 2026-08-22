from django.core.management.base import BaseCommand

from asistencia.resolver import procesar_marcaciones_pendientes


class Command(BaseCommand):
    help = (
        "Asocia las marcaciones biométricas pendientes a su Asignación (curso/aula/horario) "
        "correspondiente. Pensado para correr justo después de sync_biometrico."
    )

    def handle(self, *args, **options):
        resultados = procesar_marcaciones_pendientes()
        if not resultados:
            self.stdout.write("No había marcaciones pendientes por procesar.")
            return
        self.stdout.write(self.style.SUCCESS("Procesamiento de marcaciones completado:"))
        for clave, valor in resultados.items():
            self.stdout.write(f"  {clave}: {valor}")
