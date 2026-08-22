from datetime import time
from django.db import migrations


GRILLA = [
    (1, time(8, 0), time(8, 45), "CLASE"),
    (2, time(8, 45), time(9, 30), "CLASE"),
    (3, time(9, 30), time(9, 40), "RECESO"),
    (4, time(9, 40), time(10, 25), "CLASE"),
    (5, time(10, 25), time(11, 10), "CLASE"),
    (6, time(11, 10), time(11, 20), "RECESO"),
    (7, time(11, 20), time(12, 5), "CLASE"),
    (8, time(12, 5), time(12, 50), "CLASE"),
    (9, time(12, 50), time(15, 0), "ALMUERZO"),
    (10, time(15, 0), time(15, 45), "CLASE"),
    (11, time(15, 45), time(16, 30), "CLASE"),
    (12, time(16, 30), time(16, 40), "RECESO"),
    (13, time(16, 40), time(17, 25), "CLASE"),
    (14, time(17, 25), time(18, 10), "CLASE"),
]


def seed(apps, schema_editor):
    HoraPedagogica = apps.get_model("asistencia", "HoraPedagogica")
    for numero, inicio, fin, tipo in GRILLA:
        HoraPedagogica.objects.update_or_create(
            numero_bloque=numero,
            defaults={"hora_inicio": inicio, "hora_fin": fin, "tipo": tipo},
        )


def unseed(apps, schema_editor):
    HoraPedagogica = apps.get_model("asistencia", "HoraPedagogica")
    HoraPedagogica.objects.filter(numero_bloque__in=[n for n, *_ in GRILLA]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("asistencia", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
