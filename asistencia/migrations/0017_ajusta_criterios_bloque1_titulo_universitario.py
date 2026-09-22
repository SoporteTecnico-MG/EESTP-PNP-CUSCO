from django.db import migrations


# Ajuste al Bloque 1 (Grados y Títulos) para que la suma de topes cuadre
# exactamente en el máximo real de 20 (antes sumaba 26) y se agregue
# "Título Universitario" (Anexo 10, Civil/Extranjero) como alternativa a
# "Título Profesional en Administración y CC. Policiales" (Anexo 13,
# PNP/FFAA) — es la MISMA casilla del postulante, el puntaje que se le da
# depende de la Procedencia, así que estos dos criterios nunca se suman
# entre sí (ver Postulante.puntaje_grados_titulos).
#
# (clave, etiqueta, orden, puntaje_por_unidad, tope)
CRITERIOS_BLOQUE1 = [
    ("tiene_titulo_profesional", "Título Profesional en Administración y CC. Policiales (Anexo 13 — PNP/FFAA)", 1, 5.0, 5.0),
    ("tiene_titulo_universitario", "Título Universitario (Anexo 10 — Civil/Extranjero)", 2, 4.0, 4.0),
    ("tiene_titulo_profesional_tecnico", "Título Profesional Técnico en ciencias policiales", 3, 3.0, 3.0),
    ("tiene_maestria", "Grado académico de Maestro", 4, 4.0, 4.0),
    ("tiene_doctorado", "Grado académico de Doctor", 5, 5.0, 5.0),
    ("tiene_segunda_especialidad", "Segunda especialidad o título de especialista", 6, 3.0, 3.0),
]


def ajustar(apps, schema_editor):
    CriterioPuntaje = apps.get_model("asistencia", "CriterioPuntaje")
    for clave, etiqueta, orden, unidad, tope in CRITERIOS_BLOQUE1:
        CriterioPuntaje.objects.update_or_create(
            clave=clave,
            defaults={
                "etiqueta": etiqueta,
                "bloque": 1,
                "orden": orden,
                "puntaje_por_unidad": unidad,
                "tope": tope,
            },
        )


def revertir(apps, schema_editor):
    CriterioPuntaje = apps.get_model("asistencia", "CriterioPuntaje")
    anteriores = {
        "tiene_titulo_profesional": (1, 5.0, 5.0),
        "tiene_titulo_profesional_tecnico": (2, 4.0, 4.0),
        "tiene_maestria": (3, 6.0, 6.0),
        "tiene_doctorado": (4, 6.0, 6.0),
        "tiene_segunda_especialidad": (5, 5.0, 5.0),
    }
    for clave, (orden, unidad, tope) in anteriores.items():
        CriterioPuntaje.objects.filter(clave=clave).update(orden=orden, puntaje_por_unidad=unidad, tope=tope)
    CriterioPuntaje.objects.filter(clave="tiene_titulo_universitario").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("asistencia", "0016_decimales_conteo_y_titulo_profesional"),
    ]

    operations = [
        migrations.RunPython(ajustar, revertir),
    ]
