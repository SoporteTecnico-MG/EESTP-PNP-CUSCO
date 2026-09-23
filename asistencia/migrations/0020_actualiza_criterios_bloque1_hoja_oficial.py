from django.db import migrations


# Reemplaza los criterios del Bloque 1 por los 4 de la Hoja de Vida oficial
# (Evaluación de la Hoja de Vida de Postulantes a Plaza de Docentes):
# 5 + 4 + 6 + 5 = 20.
CRITERIOS_BLOQUE1 = [
    ("tiene_titulo_profesional", "Título Profesional en Administración y Ciencias Policiales", 1, 5.0, 5.0),
    ("tiene_titulo_tecnico_o_civil", "Título profesional Técnico en ciencias policiales / profesional civil", 2, 4.0, 4.0),
    ("tiene_maestria_o_doctorado", "Grado académico de Maestro/Doctor", 3, 6.0, 6.0),
    ("tiene_segunda_especialidad", "Segunda Especialidad o Título de Especialista de acuerdo a la naturaleza de la UD", 4, 5.0, 5.0),
]

CLAVES_OBSOLETAS = [
    "tiene_titulo_universitario",
    "tiene_titulo_profesional_tecnico",
    "tiene_maestria",
    "tiene_doctorado",
]


def actualizar(apps, schema_editor):
    CriterioPuntaje = apps.get_model("asistencia", "CriterioPuntaje")
    CriterioPuntaje.objects.filter(clave__in=CLAVES_OBSOLETAS).delete()
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
    CriterioPuntaje.objects.filter(clave__in=["tiene_titulo_tecnico_o_civil", "tiene_maestria_o_doctorado"]).delete()
    CriterioPuntaje.objects.filter(clave="tiene_titulo_profesional").update(puntaje_por_unidad=5.0, tope=5.0, orden=1)
    CriterioPuntaje.objects.filter(clave="tiene_segunda_especialidad").update(puntaje_por_unidad=3.0, tope=3.0, orden=6)


class Migration(migrations.Migration):

    dependencies = [
        ("asistencia", "0019_corrige_bloque1_segun_hoja_oficial"),
    ]

    operations = [
        migrations.RunPython(actualizar, revertir),
    ]
