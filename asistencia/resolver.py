"""
Motor de resolución de asistencia.

El horario (día/hora) vive en OfertaCurso.bloques — es el mismo para todas las
aulas/secciones que dicten ese curso en ese período. Lo que varía por aula es
la Asignación (qué docente lo dicta ahí). Por eso, para saber "qué le toca hoy
a este docente", hay que cruzar: sus Asignaciones -> el curso de cada una ->
los bloques de ese curso hoy.

Dos momentos de ejecución (ver plan del proyecto):
1. procesar_marcaciones_pendientes(): se corre después de cada sincronización con el
   biométrico (cada 5-10 min). Intenta asociar cada marcación nueva al bloque
   más cercano dentro de la tolerancia configurada.
2. cerrar_dia(fecha): se corre una vez terminado el horario del día (ej. después de
   las 18:10 + margen). Define el estado final de cada Asignación programada ese día
   para cada docente, incluyendo los casos de marcación parcial o falta total.
"""

from collections import Counter
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .models import Asignacion, AsistenciaResuelta, BloqueHorario, Docente, MarcacionBiometrica

TOLERANCIA_MINUTOS = getattr(settings, "TOLERANCIA_TARDANZA_MINUTOS", 20)


def _bloques_del_dia(docente, fecha):
    """Pares (bloque, asignación) vigentes hoy para este docente, cruzando sus
    Asignaciones con los bloques de horario del curso correspondiente."""
    dia_semana = fecha.isoweekday()
    bloques = (
        BloqueHorario.objects.filter(
            dia_semana=dia_semana,
            oferta_curso__periodo_academico__fecha_inicio__lte=fecha,
            oferta_curso__periodo_academico__fecha_fin__gte=fecha,
            oferta_curso__asignaciones__docente=docente,
        )
        .select_related("oferta_curso", "hora_pedagogica_inicio", "hora_pedagogica_fin")
        .distinct()
    )
    pares = []
    for bloque in bloques:
        for asignacion in Asignacion.objects.filter(docente=docente, oferta_curso=bloque.oferta_curso):
            pares.append((bloque, asignacion))
    return pares


def _dt_aware(fecha, hora):
    dt = datetime.combine(fecha, hora)
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def procesar_marcaciones_pendientes():
    """Asocia marcaciones nuevas (sin entrada ni salida asignada) a su Asignación."""
    tolerancia = timedelta(minutes=TOLERANCIA_MINUTOS)
    pendientes = MarcacionBiometrica.objects.filter(
        asistencias_como_entrada__isnull=True,
        asistencias_como_salida__isnull=True,
    ).order_by("timestamp")

    resultados = Counter()

    for marcacion in pendientes:
        try:
            docente = Docente.objects.get(id_biometrico=marcacion.id_biometrico)
        except Docente.DoesNotExist:
            # No es un docente (puede ser alumno u otro personal enrolado en el
            # mismo equipo compartido) — no corresponde al control de asistencia docente.
            resultados["no_docente"] += 1
            continue

        fecha = timezone.localtime(marcacion.timestamp).date()
        candidatos = []
        for bloque, asignacion in _bloques_del_dia(docente, fecha):
            inicio_dt = _dt_aware(fecha, bloque.hora_pedagogica_inicio.hora_inicio)
            fin_dt = _dt_aware(fecha, bloque.hora_pedagogica_fin.hora_fin)
            if (inicio_dt - tolerancia) <= marcacion.timestamp <= (fin_dt + tolerancia):
                candidatos.append((asignacion, inicio_dt, fin_dt))

        if not candidatos:
            ar, _ = AsistenciaResuelta.objects.get_or_create(
                docente=docente,
                asignacion=None,
                fecha=fecha,
                defaults={
                    "estado": AsistenciaResuelta.Estado.NO_PROGRAMADO,
                    "requiere_revision": True,
                },
            )
            if ar.marcacion_entrada_id is None:
                ar.marcacion_entrada = marcacion
                ar.save(update_fields=["marcacion_entrada"])
            resultados["no_programado"] += 1
            continue

        if len(candidatos) > 1:
            for asignacion, _inicio_dt, _fin_dt in candidatos:
                ar, creado = AsistenciaResuelta.objects.get_or_create(
                    docente=docente,
                    asignacion=asignacion,
                    fecha=fecha,
                    defaults={
                        "estado": AsistenciaResuelta.Estado.AMBIGUO,
                        "requiere_revision": True,
                    },
                )
                if not creado and ar.estado != AsistenciaResuelta.Estado.AMBIGUO:
                    ar.estado = AsistenciaResuelta.Estado.AMBIGUO
                    ar.requiere_revision = True
                    ar.save(update_fields=["estado", "requiere_revision"])
            resultados["ambiguo"] += 1
            continue

        asignacion, inicio_dt, fin_dt = candidatos[0]
        ar, _ = AsistenciaResuelta.objects.get_or_create(
            docente=docente,
            asignacion=asignacion,
            fecha=fecha,
            defaults={"estado": AsistenciaResuelta.Estado.FALTA},
        )
        if ar.estado == AsistenciaResuelta.Estado.AMBIGUO:
            # Ya estaba marcado ambiguo por otra marcación del mismo día; no se toca.
            resultados["ambiguo"] += 1
            continue

        dist_inicio = abs((marcacion.timestamp - inicio_dt).total_seconds())
        dist_fin = abs((marcacion.timestamp - fin_dt).total_seconds())

        if ar.marcacion_entrada_id is None and (
            dist_inicio <= dist_fin or ar.marcacion_salida_id is not None
        ):
            ar.marcacion_entrada = marcacion
            ar.save(update_fields=["marcacion_entrada"])
            resultados["asociada_entrada"] += 1
        elif ar.marcacion_salida_id is None:
            ar.marcacion_salida = marcacion
            ar.save(update_fields=["marcacion_salida"])
            resultados["asociada_salida"] += 1
        else:
            # Ambos casilleros ya ocupados (marcación duplicada de más para ese bloque).
            resultados["excedente"] += 1

    return dict(resultados)


def cerrar_dia(fecha):
    """Determina el estado final de asistencia de todas las Asignaciones del día."""
    dia_semana = fecha.isoweekday()
    bloques = list(
        BloqueHorario.objects.filter(
            dia_semana=dia_semana,
            oferta_curso__periodo_academico__fecha_inicio__lte=fecha,
            oferta_curso__periodo_academico__fecha_fin__gte=fecha,
        ).select_related("oferta_curso", "hora_pedagogica_inicio", "hora_pedagogica_fin")
    )

    bloques_por_oferta = {}
    for bloque in bloques:
        bloques_por_oferta.setdefault(bloque.oferta_curso_id, []).append(bloque)

    asignaciones = Asignacion.objects.filter(
        oferta_curso_id__in=bloques_por_oferta.keys()
    ).select_related("docente")

    resumen = Counter()
    tolerancia = timedelta(minutes=TOLERANCIA_MINUTOS)

    for asignacion in asignaciones:
        bloques_asignacion = bloques_por_oferta[asignacion.oferta_curso_id]
        docente = asignacion.docente
        inicio_dt = min(
            _dt_aware(fecha, b.hora_pedagogica_inicio.hora_inicio) for b in bloques_asignacion
        )
        fin_dt = max(
            _dt_aware(fecha, b.hora_pedagogica_fin.hora_fin) for b in bloques_asignacion
        )

        ar, _ = AsistenciaResuelta.objects.get_or_create(
            docente=docente,
            asignacion=asignacion,
            fecha=fecha,
            defaults={"estado": AsistenciaResuelta.Estado.FALTA},
        )

        if ar.estado == AsistenciaResuelta.Estado.AMBIGUO:
            resumen["ambiguo"] += 1
            continue

        tiene_entrada = ar.marcacion_entrada_id is not None
        tiene_salida = ar.marcacion_salida_id is not None

        if tiene_entrada and tiene_salida:
            minutos_tarde = max(
                0, int((ar.marcacion_entrada.timestamp - inicio_dt).total_seconds() // 60)
            )
            ar.minutos_tardanza = minutos_tarde
            ar.estado = (
                AsistenciaResuelta.Estado.TARDANZA
                if (ar.marcacion_entrada.timestamp - inicio_dt) > tolerancia
                else AsistenciaResuelta.Estado.PUNTUAL
            )
            horas_efectivas = (
                ar.marcacion_salida.timestamp - ar.marcacion_entrada.timestamp
            ).total_seconds() / 3600
            ar.horas_efectivas = round(max(0, horas_efectivas), 2)
            ar.requiere_revision = False
        elif tiene_entrada and not tiene_salida:
            minutos_tarde = max(
                0, int((ar.marcacion_entrada.timestamp - inicio_dt).total_seconds() // 60)
            )
            ar.minutos_tardanza = minutos_tarde
            ar.estado = AsistenciaResuelta.Estado.SOLO_ENTRADA
            ar.requiere_revision = True
        elif tiene_salida and not tiene_entrada:
            ar.estado = AsistenciaResuelta.Estado.SOLO_SALIDA
            ar.requiere_revision = True
        else:
            ar.estado = AsistenciaResuelta.Estado.FALTA
            ar.minutos_tardanza = 0
            ar.horas_efectivas = 0
            ar.requiere_revision = False

        ar.save()
        resumen[ar.estado] += 1

    return dict(resumen)
