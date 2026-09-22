from django.db import migrations


CRITERIOS = [
    # (clave, etiqueta, bloque, orden, puntaje_por_unidad, tope)
    ("tiene_titulo_profesional", "Título Profesional en Administración y CC. Policiales", 1, 1, 5.0, 5.0),
    ("tiene_titulo_profesional_tecnico", "Título Profesional Técnico en ciencias policiales", 1, 2, 4.0, 4.0),
    ("tiene_maestria", "Grado académico de Maestro", 1, 3, 6.0, 6.0),
    ("tiene_doctorado", "Grado académico de Doctor", 1, 4, 6.0, 6.0),
    ("tiene_segunda_especialidad", "Segunda especialidad o título de especialista", 1, 5, 5.0, 5.0),
    ("diplomados_120h", "Diplomados afines ≥120h", 2, 1, 1.0, 2.0),
    ("programas_16_96h_afines", "Programas afines 16-96h", 2, 2, 0.5, 1.0),
    ("ponente_eventos", "Ponente en eventos académicos", 3, 1, 0.5, 0.5),
    ("asistente_eventos", "Asistente a eventos académicos", 3, 2, 0.5, 0.5),
    ("investigaciones", "Investigaciones en la especialidad", 3, 3, 1.0, 1.0),
    ("publicaciones", "Textos y/o libros publicados", 3, 4, 1.0, 1.0),
    ("programas_96h_otros", "Programas ≥96h", 4, 1, 1.0, 2.0),
    ("programas_16_96h_otros", "Programas 16-96h", 4, 2, 0.5, 1.0),
    ("cursos_ofimatica_24h", "Cursos de ofimática ≥24h", 4, 3, 0.5, 1.0),
    ("pregrado_ciclos", "Docencia nivel pregrado, en ciclos", 5, 1, 0.5, 3.0),
    ("maestria_cursos", "Docencia posgrado Maestría, en cursos", 5, 2, 0.5, 1.0),
    ("experiencia_profesional_anios", "Ejercicio profesional no docente, en años", 6, 1, 1.0, 6.0),
]


def crear_criterios(apps, schema_editor):
    CriterioPuntaje = apps.get_model("asistencia", "CriterioPuntaje")
    for clave, etiqueta, bloque, orden, unidad, tope in CRITERIOS:
        CriterioPuntaje.objects.get_or_create(
            clave=clave,
            defaults={
                "etiqueta": etiqueta,
                "bloque": bloque,
                "orden": orden,
                "puntaje_por_unidad": unidad,
                "tope": tope,
            },
        )


def eliminar_criterios(apps, schema_editor):
    CriterioPuntaje = apps.get_model("asistencia", "CriterioPuntaje")
    claves = [c[0] for c in CRITERIOS]
    CriterioPuntaje.objects.filter(clave__in=claves).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("asistencia", "0014_criteriopuntaje_alter_postulante_grado"),
    ]

    operations = [
        migrations.RunPython(crear_criterios, eliminar_criterios),
    ]
