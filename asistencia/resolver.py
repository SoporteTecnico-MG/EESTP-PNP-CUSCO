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
from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from .models import (
    Asignacion,
    AsistenciaResuelta,
    BloqueHorario,
    Docente,
    HoraPedagogica,
    MarcacionBiometrica,
)

TOLERANCIA_MINUTOS = getattr(settings, "TOLERANCIA_TARDANZA_MINUTOS", 20)
DESCUENTO_TARDANZA_MINUTOS = getattr(settings, "DESCUENTO_TARDANZA_MINUTOS", 15)
BRECHA_MAXIMA_ENTRE_BLOQUES_MINUTOS = getattr(settings, "BRECHA_MAXIMA_ENTRE_BLOQUES_MINUTOS", 120)
RECUPERACION_HASTA = time(22, 0)


def _fin_horario_institucional():
    """Hora de fin de la última hora pedagógica de CLASE del día (ej. 18:10) —
    a partir de ahí y hasta las 22:00 cuenta como recuperación nocturna,
    en cualquier día, así no le toque clase ese día."""
    ultima = HoraPedagogica.objects.filter(tipo="CLASE").order_by("-numero_bloque").first()
    return ultima.hora_fin if ultima else time(18, 10)


def _horas_pedagogicas_transcurridas(fecha, bloques_asignacion, momento):
    """Cuenta cuántas horas pedagógicas (de clase) dentro de estos bloques ya
    habían terminado por completo antes de `momento` — son las que se pierden
    cuando la tardanza de entrada llega o pasa el umbral de descuento."""
    total = 0
    for b in bloques_asignacion:
        horas = HoraPedagogica.objects.filter(
            tipo="CLASE",
            numero_bloque__gte=b.hora_pedagogica_inicio.numero_bloque,
            numero_bloque__lte=b.hora_pedagogica_fin.numero_bloque,
        )
        for hp in horas:
            if _dt_aware(fecha, hp.hora_fin) <= momento:
                total += 1
    return total


def _horas_pedagogicas_totales_del_bloque(bloques_asignacion):
    """Total de horas pedagógicas (de clase) de la sesión de hoy — se pierden
    todas cuando el docente falta por completo (no marcó nada)."""
    total = 0
    for b in bloques_asignacion:
        total += HoraPedagogica.objects.filter(
            tipo="CLASE",
            numero_bloque__gte=b.hora_pedagogica_inicio.numero_bloque,
            numero_bloque__lte=b.hora_pedagogica_fin.numero_bloque,
        ).count()
    return total


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


def _deduplicar_marcas(marcas, umbral_minutos=1):
    """El biométrico a veces registra una doble lectura del mismo toque
    (mismo instante o +-1 minuto) — se cuenta como una sola marcación real,
    para no confundir un doble-toque con una entrada Y una salida."""
    umbral = timedelta(minutes=umbral_minutos)
    resultado = []
    for marca in marcas:
        if resultado and (marca.timestamp - resultado[-1].timestamp) <= umbral:
            continue
        resultado.append(marca)
    return resultado


def _dt_aware(fecha, hora):
    dt = datetime.combine(fecha, hora)
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _actualizar_estado_provisional(ar, inicio_dt, fin_dt):
    """Recalcula Puntual/Tardanza/Solo entrada/Solo salida apenas se vincula
    una marca real, para que el calendario muestre el estado correcto durante
    el día — antes se quedaba en el "Falta" por defecto hasta el cierre de
    las 23:00, aunque ya hubiera una hora de entrada real registrada. El
    cierre diario (cerrar_dia) sigue siendo el único que marca Falta total
    (con el descuento de horas pedagógicas) para quien de plano no marcó
    nada, y el único que recalcula el descuento por tardanza (necesita ver
    todos los bloques de la Asignación juntos, no uno por uno)."""
    if ar.corregido_manualmente or ar.estado == AsistenciaResuelta.Estado.AMBIGUO:
        return

    tiene_entrada = ar.marcacion_entrada_id is not None
    tiene_salida = ar.marcacion_salida_id is not None
    if not tiene_entrada and not tiene_salida:
        return

    ar.salida_anticipada = False

    if tiene_entrada and tiene_salida:
        minutos_tarde = max(
            0, int((ar.marcacion_entrada.timestamp - inicio_dt).total_seconds() // 60)
        )
        ar.minutos_tardanza = minutos_tarde
        ar.estado = (
            AsistenciaResuelta.Estado.TARDANZA
            if (ar.marcacion_entrada.timestamp - inicio_dt) > timedelta(minutes=TOLERANCIA_MINUTOS)
            else AsistenciaResuelta.Estado.PUNTUAL
        )
        horas_efectivas = (
            ar.marcacion_salida.timestamp - ar.marcacion_entrada.timestamp
        ).total_seconds() / 3600
        ar.horas_efectivas = round(max(0, horas_efectivas), 2)
        if (fin_dt - ar.marcacion_salida.timestamp) > timedelta(minutes=1):
            ar.salida_anticipada = True
        ar.requiere_revision = ar.salida_anticipada
    elif tiene_entrada:
        minutos_tarde = max(
            0, int((ar.marcacion_entrada.timestamp - inicio_dt).total_seconds() // 60)
        )
        ar.minutos_tardanza = minutos_tarde
        ar.estado = AsistenciaResuelta.Estado.SOLO_ENTRADA
        ar.requiere_revision = True
    else:
        ar.estado = AsistenciaResuelta.Estado.SOLO_SALIDA
        ar.requiere_revision = True

    ar.save()


def procesar_marcaciones_pendientes():
    """Asocia marcaciones nuevas a las Asignaciones del docente ese día.

    Modelo: un docente marca UNA vez al llegar y UNA vez al irse en el día,
    sin importar cuántos bloques dicte — incluso si son de promociones
    distintas que caen el mismo día (ej. AGUERRIDOS a las 08:00 y JUSTICIEROS
    a las 12:05). Por eso ya no se busca "la marca más cercana a cada
    bloque": la PRIMERA marca del día es su entrada y la ÚLTIMA es su salida,
    y esas dos se usan para evaluar TODOS los bloques que tenga programados
    ese día (cerrar_dia compara esa misma entrada/salida contra el horario
    de cada bloque por separado, así que la puntualidad de cada uno sigue
    siendo independiente)."""
    pendientes = (
        MarcacionBiometrica.objects.filter(
            asistencias_como_entrada__isnull=True,
            asistencias_como_salida__isnull=True,
        )
        .exclude(origen_dispositivo="MANUAL")
        .order_by("timestamp")
    )

    resultados = Counter()

    # Agrupar por (docente, fecha) para resolver juntas todas las marcas
    # pendientes de un mismo día, aunque hayan llegado en corridas distintas.
    por_docente_fecha = {}
    docentes_cache = {}
    for marcacion in pendientes:
        docente = docentes_cache.get(marcacion.id_biometrico, "no_encontrado")
        if docente == "no_encontrado":
            docente = Docente.objects.filter(id_biometrico=marcacion.id_biometrico).first()
            docentes_cache[marcacion.id_biometrico] = docente
        if docente is None:
            # No es un docente (puede ser alumno u otro personal enrolado en
            # el mismo equipo compartido) — no corresponde a este control.
            resultados["no_docente"] += 1
            continue
        fecha = timezone.localtime(marcacion.timestamp).date()
        por_docente_fecha.setdefault((docente.id, fecha), docente)

    # Bloques "huérfanos": un docente puede tener dos cursos el mismo día (a
    # veces de promociones distintas) — si uno de esos bloques se programó
    # DESPUÉS de que las marcas de ese día ya se hubieran repartido a otro
    # bloque, sus marcas ya no aparecen como "pendientes" y ese segundo
    # bloque se queda en Falta aunque el docente sí marcó. Se detectan estos
    # casos y se vuelven a procesar con todas las marcas reales del día.
    huerfanos = AsistenciaResuelta.objects.filter(
        estado=AsistenciaResuelta.Estado.FALTA,
        asignacion__isnull=False,
        marcacion_entrada__isnull=True,
    ).values_list("docente_id", "fecha").distinct()
    for docente_id, fecha in huerfanos:
        if (docente_id, fecha) in por_docente_fecha:
            continue
        docente = Docente.objects.filter(id=docente_id).first()
        if docente is None:
            continue
        tiene_marcas = MarcacionBiometrica.objects.filter(
            id_biometrico=docente.id_biometrico, timestamp__date=fecha
        ).exists()
        if tiene_marcas:
            por_docente_fecha[(docente_id, fecha)] = docente

    for (docente_id, fecha), docente in por_docente_fecha.items():
        pares = _bloques_del_dia(docente, fecha)

        if not pares:
            # No tiene nada programado ese día en ninguna promoción.
            marcas_del_dia = MarcacionBiometrica.objects.filter(
                id_biometrico=docente.id_biometrico, timestamp__date=fecha
            ).order_by("timestamp")
            primera = marcas_del_dia.first()

            # Recuperación nocturna: si marcó entrada entre el fin del
            # horario normal (ej. 18:10) y las 22:00, cuenta como
            # recuperación aunque ese día no le tocara clase — basta con
            # que haya marcado la entrada, no hace falta la salida.
            es_recuperacion = False
            if primera:
                hora_marca = timezone.localtime(primera.timestamp).time()
                es_recuperacion = _fin_horario_institucional() <= hora_marca <= RECUPERACION_HASTA

            ar, creado = AsistenciaResuelta.objects.get_or_create(
                docente=docente,
                asignacion=None,
                fecha=fecha,
                defaults={
                    "estado": AsistenciaResuelta.Estado.RECUPERACION
                    if es_recuperacion
                    else AsistenciaResuelta.Estado.NO_PROGRAMADO,
                    "requiere_revision": not es_recuperacion,
                },
            )
            if not creado and es_recuperacion and ar.estado != AsistenciaResuelta.Estado.RECUPERACION:
                ar.estado = AsistenciaResuelta.Estado.RECUPERACION
                ar.requiere_revision = False
                ar.save(update_fields=["estado", "requiere_revision"])
            if primera and ar.marcacion_entrada_id is None:
                ar.marcacion_entrada = primera
                ar.save(update_fields=["marcacion_entrada"])
            resultados["no_programado"] += 1
            continue

        todas_las_marcas = _deduplicar_marcas(
            MarcacionBiometrica.objects.filter(
                id_biometrico=docente.id_biometrico, timestamp__date=fecha
            ).order_by("timestamp")
        )
        if not todas_las_marcas:
            continue

        primera = todas_las_marcas[0]
        ultima = todas_las_marcas[-1]

        brecha_maxima = timedelta(minutes=BRECHA_MAXIMA_ENTRE_BLOQUES_MINUTOS)

        for bloque, asignacion in pares:
            # La entrada/salida del día solo se le aplica a un bloque si la
            # brecha hasta la marca real es razonable (ej. un curso a las
            # 12:05 tras marcar entrada a las 08:14 sí cuenta — la brecha es
            # corta). Si el bloque queda muy separado de toda marca del día
            # (ej. un curso de tarde cuando el docente solo marcó en la
            # mañana y no volvió en horas), no se le presta la marca de otro
            # curso: se deja sin marcar, para que salga Falta y no un falso
            # Puntual.
            inicio_dt = _dt_aware(fecha, bloque.hora_pedagogica_inicio.hora_inicio)
            fin_dt = _dt_aware(fecha, bloque.hora_pedagogica_fin.hora_fin)
            dentro_del_rango = (
                inicio_dt <= ultima.timestamp + brecha_maxima
                and fin_dt >= primera.timestamp - brecha_maxima
            )
            if not dentro_del_rango:
                continue

            ar, _ = AsistenciaResuelta.objects.get_or_create(
                docente=docente,
                asignacion=asignacion,
                fecha=fecha,
                defaults={"estado": AsistenciaResuelta.Estado.FALTA},
            )
            cambios = []

            if len(todas_las_marcas) == 1:
                # Una sola marca en todo el día: puede ser entrada o salida,
                # según a qué extremo del horario programado (el bloque más
                # temprano o el más tardío, de TODOS sus bloques de hoy) le
                # cae más cerca.
                inicio_mas_temprano = min(
                    _dt_aware(fecha, b.hora_pedagogica_inicio.hora_inicio) for b, _ in pares
                )
                fin_mas_tardio = max(
                    _dt_aware(fecha, b.hora_pedagogica_fin.hora_fin) for b, _ in pares
                )
                dist_inicio = abs((primera.timestamp - inicio_mas_temprano).total_seconds())
                dist_fin = abs((primera.timestamp - fin_mas_tardio).total_seconds())
                if dist_inicio <= dist_fin:
                    if ar.marcacion_entrada_id is None or ar.marcacion_entrada.origen_dispositivo != "MANUAL":
                        if ar.marcacion_entrada_id != primera.id:
                            ar.marcacion_entrada = primera
                            cambios.append("marcacion_entrada")
                else:
                    if ar.marcacion_salida_id is None or ar.marcacion_salida.origen_dispositivo != "MANUAL":
                        if ar.marcacion_salida_id != primera.id:
                            ar.marcacion_salida = primera
                            cambios.append("marcacion_salida")
            else:
                if ar.marcacion_entrada_id is None or ar.marcacion_entrada.origen_dispositivo != "MANUAL":
                    if ar.marcacion_entrada_id != primera.id:
                        ar.marcacion_entrada = primera
                        cambios.append("marcacion_entrada")
                if ar.marcacion_salida_id is None or ar.marcacion_salida.origen_dispositivo != "MANUAL":
                    if ar.marcacion_salida_id != ultima.id:
                        ar.marcacion_salida = ultima
                        cambios.append("marcacion_salida")

            if cambios:
                ar.save(update_fields=cambios)
            _actualizar_estado_provisional(ar, inicio_dt, fin_dt)
            resultados["vinculada"] += 1

    return dict(resultados)


def cerrar_dia(fecha):
    """Determina el estado final de asistencia de todas las Asignaciones del día.
    Si la fecha es feriado nacional o suspensión por disposición superior, no hay
    obligación de marcar — no se genera ni se toca ningún registro ese día."""
    from .models import Feriado

    if Feriado.objects.filter(fecha=fecha).exists():
        return {}

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

        if ar.corregido_manualmente:
            resumen[ar.estado] += 1
            continue

        tiene_entrada = ar.marcacion_entrada_id is not None
        tiene_salida = ar.marcacion_salida_id is not None

        ar.horas_pedagogicas_descontadas = 0
        ar.salida_anticipada = False

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

            # Descuento automático: 15+ min de tardanza -> se pierden las horas
            # pedagógicas que ya habían terminado por completo al momento de entrar.
            if minutos_tarde >= DESCUENTO_TARDANZA_MINUTOS:
                ar.horas_pedagogicas_descontadas = _horas_pedagogicas_transcurridas(
                    fecha, bloques_asignacion, ar.marcacion_entrada.timestamp
                )

            # Salida anticipada: no se descuenta sola, solo se marca para que
            # jefatura decida.
            if (fin_dt - ar.marcacion_salida.timestamp) > timedelta(minutes=1):
                ar.salida_anticipada = True

            ar.requiere_revision = ar.salida_anticipada
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
            ar.horas_pedagogicas_descontadas = _horas_pedagogicas_totales_del_bloque(bloques_asignacion)

        ar.save()
        resumen[ar.estado] += 1

    return dict(resumen)
