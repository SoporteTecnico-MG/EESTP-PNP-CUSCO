import hashlib
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.db.models import Q, ProtectedError
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .models import (
    Asignacion,
    AsistenciaResuelta,
    Aula,
    BloqueHorario,
    Curso,
    Docente,
    Especialidad,
    Feriado,
    HoraPedagogica,
    MarcacionBiometrica,
    OfertaCurso,
    PeriodoAcademico,
    Postulante,
    Promocion,
    registrar_actividad,
)

NOMBRE_ESCUELA_CORTO = "EESTP PNP CUSCO"
NOMBRE_ESCUELA_LARGO = "Escuela de Educación Superior Técnico Profesional PNP Cusco"

DIAS = list(BloqueHorario.Dia.choices)


def _segmentos_de_clase(ini, fin, horas_por_numero):
    """Dado un rango [ini, fin] de números de bloque, lo parte en tramos contiguos
    de SOLO horas de clase, cortando en cada receso/almuerzo que haya en medio.
    Así un curso que cruza un receso se dibuja como 2+ bloques separados, con el
    receso visible entre ellos, en vez de tragárselo con un solo rowspan largo."""
    segmentos = []
    inicio_seg = None
    fin_seg = None
    for n in range(ini, fin + 1):
        hp = horas_por_numero.get(n)
        if hp and hp.tipo == "CLASE":
            if inicio_seg is None:
                inicio_seg = n
            fin_seg = n
        elif inicio_seg is not None:
            segmentos.append((inicio_seg, fin_seg))
            inicio_seg = None
    if inicio_seg is not None:
        segmentos.append((inicio_seg, fin_seg))
    return segmentos


def home(request):
    """Página pública institucional: info de la EESTP + convocatorias (a llenar más
    adelante) + acceso a iniciar sesión. No requiere estar logueado."""
    return render(request, "asistencia/home.html")


def nosotros(request):
    """Página pública aparte: reseña histórica, misión/visión y formación académica."""
    return render(request, "asistencia/nosotros.html")


def convocatorias(request):
    """Página pública aparte: avisos y convocatorias institucionales."""
    return render(request, "asistencia/convocatorias.html")


def contacto(request):
    """Página pública aparte: cómo comunicarse con la escuela."""
    return render(request, "asistencia/contacto.html")


@login_required
def post_login_redirect(request):
    """Después de iniciar sesión, cada rol va a lo suyo: administradores al control
    total (admin/Control Docentes), docentes y estudiantes al Aula Virtual."""
    user = request.user
    if user.is_staff or user.is_superuser:
        return redirect("admin:index")
    if user.groups.filter(name="Docentes").exists():
        return redirect("asistencia:aula_virtual")
    if user.groups.filter(name="Estudiantes").exists():
        return redirect("asistencia:aula_virtual")
    return redirect("asistencia:home")


@login_required
def aula_virtual(request):
    """Marcador de posición — el Aula Virtual todavía no está construida, se
    planificará como una fase aparte."""
    return render(request, "asistencia/aula_virtual.html")


@login_required
def mi_cuenta(request):
    """Cada usuario puede editar sus propios datos personales (nombre,
    apellido, correo) y cambiar su contraseña — sin necesitar al
    administrador general para eso."""
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.forms import PasswordChangeForm

    user = request.user
    datos_form = None
    clave_form = None

    if request.method == "POST" and request.POST.get("accion") == "datos":
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()
        user.email = request.POST.get("email", "").strip()
        user.save(update_fields=["first_name", "last_name", "email"])
        registrar_actividad(request, "Actualizó sus datos personales")
        return redirect(f"{reverse('asistencia:mi_cuenta')}?ok_datos=1")

    if request.method == "POST" and request.POST.get("accion") == "clave":
        clave_form = PasswordChangeForm(user=user, data=request.POST)
        if clave_form.is_valid():
            clave_form.save()
            update_session_auth_hash(request, user)
            registrar_actividad(request, "Cambió su contraseña")
            return redirect(f"{reverse('asistencia:mi_cuenta')}?ok_clave=1")
    else:
        clave_form = PasswordChangeForm(user=user)

    return render(
        request,
        "asistencia/mi_cuenta.html",
        {
            "clave_form": clave_form,
            "ok_datos": request.GET.get("ok_datos") == "1",
            "ok_clave": request.GET.get("ok_clave") == "1",
        },
    )


def _curso_color(nombre):
    """Color pastel determinístico a partir del nombre del curso, para que el mismo
    curso siempre se vea del mismo color en toda la grilla (como en la hoja de referencia)."""
    h = int(hashlib.md5(nombre.encode("utf-8")).hexdigest(), 16)
    hue = h % 360
    return f"hsl({hue}, 55%, 82%)"


def _especialidades_de(promocion):
    """Especialidades que ya tienen aulas en esta promoción (vacío en I/II período,
    antes de la división por especialidad)."""
    return Especialidad.objects.filter(aula__promocion=promocion).distinct().order_by("nombre")


def _aulas_del_grupo(promocion, especialidad):
    """Aulas a las que les corresponde este horario: las de esa especialidad, o
    todas (si todavía no hay división por especialidad en esta promoción)."""
    if especialidad:
        return Aula.objects.filter(promocion=promocion, especialidad=especialidad)
    return Aula.objects.filter(promocion=promocion, especialidad__isnull=True)


def _ofertas_disponibles(periodo, especialidad):
    """Ofertas de curso de este período que le corresponden a este grupo (comunes +
    las propias de la especialidad). El horario que se le fije es compartido por
    TODAS las aulas de este grupo — por eso se programa una sola vez aquí."""
    q = Q(curso__especialidad__isnull=True)
    if especialidad:
        q |= Q(curso__especialidad=especialidad)
    return OfertaCurso.objects.filter(q, periodo_academico=periodo).select_related("curso")


def _construir_grilla(aula, dias=None):
    """Grilla semanal de SOLO LECTURA de una aula puntual: lo que esa aula ya
    tiene realmente asignado (curso, docente, día/hora), sin nada para editar."""
    dias = dias if dias is not None else DIAS[:6]
    horas = list(HoraPedagogica.objects.all().order_by("numero_bloque"))
    ofertas_ids = list(Asignacion.objects.filter(aula=aula).values_list("oferta_curso_id", flat=True))

    bloques = (
        BloqueHorario.objects.filter(oferta_curso_id__in=ofertas_ids)
        .select_related("oferta_curso__curso", "hora_pedagogica_inicio", "hora_pedagogica_fin")
        if ofertas_ids
        else []
    )
    asignaciones_aula = {
        a.oferta_curso_id: a
        for a in Asignacion.objects.filter(aula=aula, oferta_curso_id__in=ofertas_ids).select_related("docente")
    }

    horas_por_numero = {h.numero_bloque: h for h in horas}
    indice = {}
    ocupadas = set()
    for b in bloques:
        ini = b.hora_pedagogica_inicio.numero_bloque
        fin = b.hora_pedagogica_fin.numero_bloque
        color = _curso_color(b.oferta_curso.curso.nombre)
        for seg_ini, seg_fin in _segmentos_de_clase(ini, fin, horas_por_numero):
            indice[(seg_ini, b.dia_semana)] = {
                "bloque": b,
                "oferta": b.oferta_curso,
                "asignacion": asignaciones_aula.get(b.oferta_curso_id),
                "rowspan": seg_fin - seg_ini + 1,
                "color": color,
            }
            for n in range(seg_ini, seg_fin + 1):
                ocupadas.add((n, b.dia_semana))

    filas_grilla = []
    for hp in horas:
        fila = {"hora": hp, "celdas": []}
        for dia_num, dia_nombre in dias:
            clave = (hp.numero_bloque, dia_num)
            if clave in indice:
                fila["celdas"].append({"tipo": "inicio", **indice[clave]})
            elif clave in ocupadas:
                fila["celdas"].append({"tipo": "ocupada"})
            elif hp.tipo != "CLASE":
                fila["celdas"].append({"tipo": "receso", "etiqueta": hp.get_tipo_display()})
            else:
                fila["celdas"].append({"tipo": "libre_lectura"})
        filas_grilla.append(fila)

    return filas_grilla


def _construir_grilla_grupo(promocion, periodo, especialidad, dias=None):
    """Grilla semanal EDITABLE de todo un grupo (una especialidad, o 'sin
    especialidad' si la promoción todavía no se divide). El horario que se
    fija aquí es compartido por todas las aulas del grupo; lo que sí varía
    por aula es el docente, así que cada celda puede listar varios."""
    dias = dias if dias is not None else DIAS[:6]
    horas = list(HoraPedagogica.objects.all().order_by("numero_bloque"))
    horas_clase = [h for h in horas if h.tipo == "CLASE"]

    aulas_grupo = list(_aulas_del_grupo(promocion, especialidad))
    ofertas = _ofertas_disponibles(periodo, especialidad)
    ofertas_ids = list(ofertas.values_list("id", flat=True))

    bloques = (
        BloqueHorario.objects.filter(oferta_curso_id__in=ofertas_ids)
        .select_related("oferta_curso__curso", "hora_pedagogica_inicio", "hora_pedagogica_fin")
        if ofertas_ids
        else []
    )

    # Por oferta, un diccionario {aula_id: Asignacion} para poder editar el
    # docente de CADA aula del grupo directo desde la celda de la grilla.
    asignaciones_por_oferta = {}
    for a in Asignacion.objects.filter(
        oferta_curso_id__in=ofertas_ids, aula__in=aulas_grupo
    ).select_related("aula", "docente"):
        asignaciones_por_oferta.setdefault(a.oferta_curso_id, {})[a.aula_id] = a

    horas_por_numero = {h.numero_bloque: h for h in horas}
    indice = {}
    ocupadas = set()
    for b in bloques:
        ini = b.hora_pedagogica_inicio.numero_bloque
        fin = b.hora_pedagogica_fin.numero_bloque
        asignaciones_aula = asignaciones_por_oferta.get(b.oferta_curso_id, {})
        filas_aula = [
            {"aula": aula, "asignacion": asignaciones_aula.get(aula.id)} for aula in aulas_grupo
        ]
        color = _curso_color(b.oferta_curso.curso.nombre)
        for seg_ini, seg_fin in _segmentos_de_clase(ini, fin, horas_por_numero):
            indice[(seg_ini, b.dia_semana)] = {
                "bloque": b,
                "oferta": b.oferta_curso,
                "filas_aula": filas_aula,
                "rowspan": seg_fin - seg_ini + 1,
                "color": color,
            }
            for n in range(seg_ini, seg_fin + 1):
                ocupadas.add((n, b.dia_semana))

    filas_grilla = []
    for hp in horas:
        fila = {"hora": hp, "celdas": []}
        for dia_num, dia_nombre in dias:
            clave = (hp.numero_bloque, dia_num)
            if clave in indice:
                fila["celdas"].append({"tipo": "inicio", "dia": dia_num, **indice[clave]})
            elif clave in ocupadas:
                fila["celdas"].append({"tipo": "ocupada"})
            elif hp.tipo != "CLASE":
                fila["celdas"].append({"tipo": "receso", "etiqueta": hp.get_tipo_display()})
            else:
                fines_posibles = []
                for h2 in horas_clase:
                    if h2.numero_bloque < hp.numero_bloque:
                        continue
                    if h2.numero_bloque > hp.numero_bloque and (h2.numero_bloque, dia_num) in ocupadas:
                        break
                    fines_posibles.append(h2)
                fila["celdas"].append(
                    {
                        "tipo": "libre",
                        "dia": dia_num,
                        "hora_inicio_id": hp.id,
                        "fines_posibles": fines_posibles,
                    }
                )
        filas_grilla.append(fila)

    return filas_grilla


@login_required
def asignar_horario(request):
    promocion_id = request.GET.get("promocion") or request.POST.get("promocion")
    periodo_id = request.GET.get("periodo") or request.POST.get("periodo")
    especialidad_id = request.GET.get("especialidad") or request.POST.get("especialidad")

    promocion = get_object_or_404(Promocion, pk=promocion_id) if promocion_id else None
    periodo = (
        PeriodoAcademico.objects.filter(pk=periodo_id, promocion=promocion).first()
        if periodo_id and promocion
        else None
    )

    especialidades = _especialidades_de(promocion) if promocion else Especialidad.objects.none()
    especialidad = None
    grupo_listo = False
    if promocion and periodo:
        if especialidades:
            if especialidad_id:
                especialidad = get_object_or_404(Especialidad, pk=especialidad_id)
                grupo_listo = True
        else:
            # Todavía no hay división por especialidad en esta promoción: un solo grupo.
            grupo_listo = True

    # Si la promoción tiene un solo período, no hacer que el usuario lo elija aparte.
    if promocion and not periodo:
        periodos_promocion = PeriodoAcademico.objects.filter(promocion=promocion)
        if periodos_promocion.count() == 1:
            periodo = periodos_promocion.first()
            if not especialidades:
                grupo_listo = True

    mensaje = None
    error = None

    if request.method == "POST" and periodo and request.POST.get("accion") == "toggle_sabado":
        periodo.usa_sabado = not periodo.usa_sabado
        periodo.save(update_fields=["usa_sabado"])
        mensaje = "Sábado habilitado para este período." if periodo.usa_sabado else "Sábado deshabilitado para este período."
        params = f"promocion={promocion.id}&periodo={periodo.id}"
        if especialidad:
            params += f"&especialidad={especialidad.id}"
        params += f"&msg={quote(mensaje)}"
        return redirect(f"{request.path}?{params}")

    if request.method == "POST" and periodo and grupo_listo:
        accion = request.POST.get("accion")

        if accion == "programar_curso":
            # El docente se asigna aparte (ficha del docente). Aquí solo se fija el
            # horario de un curso — se programa una sola vez por período y aplica a
            # todas las aulas del grupo. Se puede volver a usar para agregar OTRO día
            # al mismo curso (ej. si dicta martes y jueves).
            curso_id = request.POST.get("curso")
            dia = request.POST.get("dia_semana")
            hp_ini_id = request.POST.get("hora_pedagogica_inicio")
            hp_fin_id = request.POST.get("hora_pedagogica_fin")

            oferta = _ofertas_disponibles(periodo, especialidad).filter(curso_id=curso_id).first()
            tiene_docente = oferta and Asignacion.objects.filter(
                oferta_curso=oferta, aula__in=_aulas_del_grupo(promocion, especialidad)
            ).exists()

            if not (curso_id and dia and hp_ini_id and hp_fin_id):
                error = "Faltan datos para programar el curso."
            elif dia == str(BloqueHorario.Dia.SABADO) and not periodo.usa_sabado:
                error = "Este período tiene el sábado deshabilitado — actívalo arriba antes de programar algo ese día."
            elif not oferta:
                error = "Ese curso no corresponde a este grupo."
            elif not tiene_docente:
                error = "Ese curso todavía no tiene docente asignado en ninguna aula de este grupo — asígnalo primero desde la ficha del docente."
            else:
                hp_ini = get_object_or_404(HoraPedagogica, pk=hp_ini_id)
                hp_fin = get_object_or_404(HoraPedagogica, pk=hp_fin_id)
                ofertas_grupo_ids = _ofertas_disponibles(periodo, especialidad).values_list("id", flat=True)
                solapa = BloqueHorario.objects.filter(
                    oferta_curso_id__in=ofertas_grupo_ids,
                    dia_semana=dia,
                    hora_pedagogica_inicio__numero_bloque__lte=hp_fin.numero_bloque,
                    hora_pedagogica_fin__numero_bloque__gte=hp_ini.numero_bloque,
                ).exists()
                if solapa:
                    error = "Ese horario se cruza con un curso que ya tiene este grupo a esa hora."
                else:
                    BloqueHorario.objects.create(
                        oferta_curso=oferta,
                        dia_semana=dia,
                        hora_pedagogica_inicio=hp_ini,
                        hora_pedagogica_fin=hp_fin,
                    )
                    mensaje = f"{oferta.curso.nombre} programado — este horario ya queda fijo para todas las aulas del grupo."

        elif accion == "quitar_bloque":
            # Quita ese día/hora del curso para TODO el grupo (es compartido).
            bloque_id = request.POST.get("bloque_id")
            ofertas_grupo_ids = _ofertas_disponibles(periodo, especialidad).values_list("id", flat=True)
            borrados, _ = BloqueHorario.objects.filter(pk=bloque_id, oferta_curso_id__in=ofertas_grupo_ids).delete()
            if borrados:
                mensaje = "Bloque eliminado para todo el grupo."
            else:
                error = "No se pudo quitar ese bloque — puede que ya no exista o no pertenezca a este grupo."

        elif accion == "asignar_docente":
            # Docente de UNA aula puntual para este curso, editable directo desde la grilla.
            oferta_id = request.POST.get("oferta_curso")
            aula_id = request.POST.get("aula_id")
            docente_id = request.POST.get("docente")
            oferta = _ofertas_disponibles(periodo, especialidad).filter(pk=oferta_id).first()
            aula = _aulas_del_grupo(promocion, especialidad).filter(pk=aula_id).first()
            if not oferta or not aula or not docente_id:
                error = "Faltan datos para asignar el docente."
            else:
                Asignacion.objects.update_or_create(
                    aula=aula, oferta_curso=oferta, defaults={"docente_id": docente_id}
                )
                mensaje = f"Docente asignado en {aula.codigo} para {oferta.curso.nombre}."

        elif accion == "guardar_docentes_curso" and request.POST.get("quitar"):
            # Se apretó el botón "×" de una fila puntual dentro del formulario
            # del curso — mismo comportamiento que "quitar_docente".
            asignacion_id = request.POST.get("quitar")
            aulas_grupo_ids = _aulas_del_grupo(promocion, especialidad).values_list("id", flat=True)
            try:
                borrados, _ = Asignacion.objects.filter(pk=asignacion_id, aula_id__in=aulas_grupo_ids).delete()
                if borrados:
                    mensaje = "Docente quitado de esa aula."
                else:
                    error = "No se pudo quitar — esa asignación ya no existe o no pertenece a este grupo."
            except ProtectedError:
                error = (
                    "No se puede quitar: esta aula ya tiene asistencias registradas con este "
                    "docente. Para cambiarlo usa el selector y el botón ↻ (reemplaza al docente "
                    "sin borrar el historial)."
                )

        elif accion == "guardar_docentes_curso":
            # Un solo formulario por curso: el botón "fila" indica si se guarda
            # una sola aula (su id) o todo el curso de una vez ("todas").
            oferta_id = request.POST.get("oferta_curso")
            oferta = _ofertas_disponibles(periodo, especialidad).filter(pk=oferta_id).first()
            fila = request.POST.get("fila")
            if not oferta or not fila:
                error = "Faltan datos para guardar el curso."
            else:
                aulas_grupo = list(_aulas_del_grupo(promocion, especialidad))
                if fila == "todas":
                    aulas_a_guardar = aulas_grupo
                else:
                    aulas_a_guardar = [a for a in aulas_grupo if str(a.id) == fila]

                guardadas = 0
                for aula in aulas_a_guardar:
                    docente_id = request.POST.get(f"docente_aula_{aula.id}")
                    if docente_id:
                        Asignacion.objects.update_or_create(
                            aula=aula, oferta_curso=oferta, defaults={"docente_id": docente_id}
                        )
                        guardadas += 1

                if guardadas:
                    mensaje = (
                        f"{guardadas} aula(s) guardada(s) para {oferta.curso.nombre}."
                        if fila == "todas"
                        else f"Docente guardado en {oferta.curso.nombre}."
                    )
                else:
                    error = "No había ningún docente seleccionado para guardar."

        elif accion == "quitar_docente":
            asignacion_id = request.POST.get("asignacion_id")
            aulas_grupo_ids = _aulas_del_grupo(promocion, especialidad).values_list("id", flat=True)
            try:
                borrados, _ = Asignacion.objects.filter(pk=asignacion_id, aula_id__in=aulas_grupo_ids).delete()
                if borrados:
                    mensaje = "Docente quitado de esa aula."
                else:
                    error = "No se pudo quitar — esa asignación ya no existe o no pertenece a este grupo."
            except ProtectedError:
                error = (
                    "No se puede quitar: esta aula ya tiene asistencias registradas con este "
                    "docente. Para cambiarlo usa el selector y el botón ↻ (reemplaza al docente "
                    "sin borrar el historial)."
                )

        params = f"promocion={promocion.id}&periodo={periodo.id}"
        if especialidad:
            params += f"&especialidad={especialidad.id}"
        if mensaje:
            params += f"&msg={quote(mensaje)}"
        if error:
            params += f"&error={quote(error)}"
        return redirect(f"{request.path}?{params}")

    dias_periodo = DIAS[:6] if (periodo and periodo.usa_sabado) else DIAS[:5]
    grilla = _construir_grilla_grupo(promocion, periodo, especialidad, dias_periodo) if grupo_listo else None

    cursos_para_programar = []
    if grupo_listo:
        aulas_grupo = _aulas_del_grupo(promocion, especialidad)
        ofertas = _ofertas_disponibles(periodo, especialidad).order_by("curso__nombre")
        for oferta in ofertas:
            asignaciones = list(
                Asignacion.objects.filter(oferta_curso=oferta, aula__in=aulas_grupo).select_related("docente")
            )
            if not asignaciones:
                continue  # nadie lo dicta todavía en este grupo, nada que programar
            dias_ya_puestos = list(
                BloqueHorario.objects.filter(oferta_curso=oferta).values_list("dia_semana", flat=True)
            )
            cursos_para_programar.append(
                {
                    "oferta": oferta,
                    "docentes": ", ".join(sorted({a.docente.apellidos_nombres for a in asignaciones})),
                    "dias_ya_puestos": [BloqueHorario.Dia(d).label for d in dias_ya_puestos],
                }
            )

    return render(
        request,
        "asistencia/asignar_horario.html",
        {
            "promociones": Promocion.objects.all(),
            "promocion": promocion,
            "periodos": PeriodoAcademico.objects.filter(promocion=promocion) if promocion else [],
            "periodo": periodo,
            "especialidades": especialidades,
            "especialidad": especialidad,
            "grupo_listo": grupo_listo,
            "grilla": grilla,
            "dias": dias_periodo,
            "cursos_para_programar": cursos_para_programar,
            "docentes": Docente.objects.filter(estado="ACTIVO").order_by("apellidos_nombres"),
            "mensaje": request.GET.get("msg"),
            "error": request.GET.get("error"),
        },
    )


@login_required
def ver_horario(request):
    promocion_id = request.GET.get("promocion")
    aula_id = request.GET.get("aula")

    promocion = get_object_or_404(Promocion, pk=promocion_id) if promocion_id else None
    aula = get_object_or_404(Aula, pk=aula_id, promocion=promocion) if aula_id else None

    periodo = None
    if aula:
        periodo = (
            PeriodoAcademico.objects.filter(ofertas_curso__asignaciones__aula=aula)
            .distinct()
            .order_by("-numero_periodo")
            .first()
        )

    dias_periodo = DIAS[:6] if (periodo and periodo.usa_sabado) else DIAS[:5]
    grilla = _construir_grilla(aula, dias_periodo) if aula else None

    return render(
        request,
        "asistencia/ver_horario.html",
        {
            "promociones": Promocion.objects.all(),
            "promocion": promocion,
            "aulas": Aula.objects.filter(promocion=promocion) if promocion else [],
            "aula": aula,
            "periodo": periodo,
            "dias": dias_periodo,
            "grilla": grilla,
        },
    )


@login_required
def reporte_asistencia(request):
    promocion_id = request.GET.get("promocion")
    periodo_id = request.GET.get("periodo")
    docente_id = request.GET.get("docente")
    curso_id = request.GET.get("curso")
    estado_filtro = request.GET.get("estado")
    if estado_filtro not in AsistenciaResuelta.Estado.values:
        estado_filtro = ""

    promocion = get_object_or_404(Promocion, pk=promocion_id) if promocion_id else None
    # Si el período pedido no pertenece a la promoción elegida (ej. quedó un
    # filtro viejo al cambiar de promoción), se ignora en vez de romper la
    # página — simplemente se trata como "sin período elegido".
    periodo = (
        PeriodoAcademico.objects.filter(pk=periodo_id, promocion=promocion).first()
        if periodo_id and promocion
        else None
    )

    if promocion and not periodo:
        periodos_promocion = PeriodoAcademico.objects.filter(promocion=promocion)
        if periodos_promocion.count() == 1:
            periodo = periodos_promocion.first()
        # Si hay más de un período y no eligió uno, se queda en None a
        # propósito: el reporte muestra TODOS los períodos de la promoción.

    fecha_desde_str = request.GET.get("fecha_desde")
    fecha_hasta_str = request.GET.get("fecha_hasta")
    fecha_desde = fecha_hasta = None
    if fecha_desde_str:
        fecha_desde = datetime.strptime(fecha_desde_str, "%Y-%m-%d").date()
    if fecha_hasta_str:
        fecha_hasta = datetime.strptime(fecha_hasta_str, "%Y-%m-%d").date()

    solo_descuento = request.GET.get("solo_descuento") == "on"

    orden = request.GET.get("orden", "fecha")
    campo_orden = orden.lstrip("-")
    reverso = orden.startswith("-")
    columnas_orden = ("fecha", "docente", "curso", "seccion", "estado")
    if campo_orden not in columnas_orden:
        campo_orden = "fecha"
    next_orden = {c: (f"-{c}" if campo_orden == c and not reverso else c) for c in columnas_orden}

    qs_sin_orden = request.GET.copy()
    qs_sin_orden.pop("orden", None)
    base_qs = qs_sin_orden.urlencode()

    filas = []
    resumen = {"puntual": 0, "tardanza": 0, "falta": 0, "recuperacion": 0, "por_revisar": 0, "horas_descontadas": 0}
    cursos_filtro = Curso.objects.none()

    if periodo:
        oferta_filtro = {"periodo_academico": periodo}
        rango_desde, rango_hasta = periodo.fecha_inicio, periodo.fecha_fin
    elif promocion:
        oferta_filtro = {"periodo_academico__promocion": promocion}
        periodos_promo = PeriodoAcademico.objects.filter(promocion=promocion)
        rango_desde = min((p.fecha_inicio for p in periodos_promo), default=None)
        rango_hasta = max((p.fecha_fin for p in periodos_promo), default=None)
    else:
        # Sin promoción elegida: reporte combinado de TODAS las promociones.
        oferta_filtro = {}
        todos_los_periodos = PeriodoAcademico.objects.all()
        rango_desde = min((p.fecha_inicio for p in todos_los_periodos), default=None)
        rango_hasta = max((p.fecha_fin for p in todos_los_periodos), default=None)

    if oferta_filtro is not None:
        cursos_filtro = Curso.objects.filter(
            ofertas__in=OfertaCurso.objects.filter(**oferta_filtro)
        ).distinct().order_by("nombre")

        feriados_qs = Feriado.objects.all()
        if rango_desde:
            feriados_qs = feriados_qs.filter(fecha__gte=rango_desde)
        if rango_hasta:
            feriados_qs = feriados_qs.filter(fecha__lte=rango_hasta)
        if fecha_desde:
            feriados_qs = feriados_qs.filter(fecha__gte=fecha_desde)
        if fecha_hasta:
            feriados_qs = feriados_qs.filter(fecha__lte=fecha_hasta)
        feriados = set(feriados_qs.values_list("fecha", flat=True))

        for fer in (feriados_qs if not (solo_descuento or estado_filtro) else []):
            filas.append(
                {
                    "es_feriado": True,
                    "fecha_sort": fer.fecha,
                    "docente_sort": "",
                    "curso": "",
                    "estado_sort": "FERIADO",
                    "hora_sort": -1,
                    "aula_sort": -1,
                    "hora_inicio_display": "",
                    "hora_fin_display": "",
                    "fecha_display": fer.fecha,
                    "descripcion": fer.descripcion,
                    "periodo_nombre": "",
                    "promocion_nombre": "",
                }
            )

        # Rango de bloques (inicio y fin, por número de hora pedagógica) de cada
        # curso en cada día de la semana — para poder ordenar el reporte igual
        # que se ve en el horario real (mañana antes que tarde) y mostrar la
        # hora exacta en la que debía empezar y terminar la clase.
        primer_bloque = {}
        ultimo_bloque = {}
        oferta_filtro_bloques = {f"oferta_curso__{k}": v for k, v in oferta_filtro.items()}
        bloques_periodo = BloqueHorario.objects.filter(**oferta_filtro_bloques).select_related(
            "hora_pedagogica_inicio", "hora_pedagogica_fin"
        )
        for b in bloques_periodo:
            clave = (b.oferta_curso_id, b.dia_semana)
            numero_ini = b.hora_pedagogica_inicio.numero_bloque
            numero_fin = b.hora_pedagogica_fin.numero_bloque
            actual_ini = primer_bloque.get(clave)
            if actual_ini is None or numero_ini < actual_ini[0]:
                primer_bloque[clave] = (numero_ini, b.hora_pedagogica_inicio.hora_inicio)
            actual_fin = ultimo_bloque.get(clave)
            if actual_fin is None or numero_fin > actual_fin[0]:
                ultimo_bloque[clave] = (numero_fin, b.hora_pedagogica_fin.hora_fin)

        oferta_filtro_registros = {f"asignacion__oferta_curso__{k}": v for k, v in oferta_filtro.items()}
        registros = (
            AsistenciaResuelta.objects.filter(**oferta_filtro_registros)
            .exclude(fecha__in=feriados)
            .select_related(
                "docente",
                "asignacion__aula",
                "asignacion__oferta_curso__curso",
                "asignacion__oferta_curso__periodo_academico__promocion",
                "marcacion_entrada",
                "marcacion_salida",
            )
            .order_by("fecha", "docente__apellidos_nombres")
        )
        if docente_id:
            registros = registros.filter(docente_id=docente_id)
        if curso_id:
            registros = registros.filter(asignacion__oferta_curso__curso_id=curso_id)
        if fecha_desde:
            registros = registros.filter(fecha__gte=fecha_desde)
        if fecha_hasta:
            registros = registros.filter(fecha__lte=fecha_hasta)
        if solo_descuento:
            registros = registros.filter(horas_pedagogicas_descontadas__gt=0)
        if estado_filtro:
            registros = registros.filter(estado=estado_filtro)

        for r in registros:
            obs = []
            if r.estado == AsistenciaResuelta.Estado.TARDANZA:
                obs.append(f"Tardanza {r.minutos_tardanza} min")
            if r.horas_pedagogicas_descontadas:
                obs.append(f"{r.horas_pedagogicas_descontadas} HP descontada(s)")
            if r.salida_anticipada:
                obs.append("Salida anticipada — revisar")
            if r.estado == AsistenciaResuelta.Estado.SOLO_ENTRADA:
                obs.append("No marcó salida")
            if r.estado == AsistenciaResuelta.Estado.SOLO_SALIDA:
                obs.append("No marcó entrada")
            if r.estado == AsistenciaResuelta.Estado.AMBIGUO:
                obs.append("Horario cruzado — revisar")
            if r.estado == AsistenciaResuelta.Estado.NO_PROGRAMADO:
                obs.append("Marcó fuera de todo horario programado")
            if r.estado == AsistenciaResuelta.Estado.RECUPERACION:
                obs.append("Recuperación nocturna")
            if r.estado == AsistenciaResuelta.Estado.FALTA:
                obs.append("Sin marcación — corregir si hubo falla del biométrico")
            if r.requiere_revision and not obs:
                obs.append("Requiere revisión")

            cumplio = r.estado in (AsistenciaResuelta.Estado.PUNTUAL, AsistenciaResuelta.Estado.RECUPERACION)

            if r.asignacion:
                clave_bloque = (r.asignacion.oferta_curso_id, r.fecha.isoweekday())
                numero_bloque, hora_inicio_bloque = primer_bloque.get(clave_bloque, (999, None))
                _, hora_fin_bloque = ultimo_bloque.get(clave_bloque, (None, None))
                aula_sort = r.asignacion.aula.numero
                per = r.asignacion.oferta_curso.periodo_academico
                periodo_nombre = per.nombre or f"{per.numero_periodo}° Periodo"
                promocion_nombre = per.promocion.nombre
            else:
                numero_bloque, hora_inicio_bloque, hora_fin_bloque = (999, None, None)
                aula_sort = 999
                periodo_nombre = "—"
                promocion_nombre = "—"

            filas.append(
                {
                    "es_feriado": False,
                    "registro": r,
                    "periodo_nombre": periodo_nombre,
                    "promocion_nombre": promocion_nombre,
                    "curso": r.asignacion.oferta_curso.curso.nombre if r.asignacion else "—",
                    "aula": r.asignacion.aula.codigo if r.asignacion else "—",
                    "hora_entrada": timezone.localtime(r.marcacion_entrada.timestamp) if r.marcacion_entrada else None,
                    "hora_salida": timezone.localtime(r.marcacion_salida.timestamp) if r.marcacion_salida else None,
                    "obs": "; ".join(obs) if obs else "—",
                    "cumplio": cumplio,
                    "fecha_sort": r.fecha,
                    "docente_sort": r.docente.apellidos_nombres,
                    "estado_sort": r.get_estado_display(),
                    "hora_sort": numero_bloque,
                    "aula_sort": aula_sort,
                    "hora_inicio_display": hora_inicio_bloque,
                    "hora_fin_display": hora_fin_bloque,
                }
            )
            if r.estado == AsistenciaResuelta.Estado.PUNTUAL:
                resumen["puntual"] += 1
            elif r.estado == AsistenciaResuelta.Estado.TARDANZA:
                resumen["tardanza"] += 1
            elif r.estado == AsistenciaResuelta.Estado.FALTA:
                resumen["falta"] += 1
            elif r.estado == AsistenciaResuelta.Estado.RECUPERACION:
                resumen["recuperacion"] += 1
            if r.requiere_revision:
                resumen["por_revisar"] += 1
            resumen["horas_descontadas"] += r.horas_pedagogicas_descontadas

        claves_orden = {
            "fecha": lambda f: (f["fecha_sort"], f["hora_sort"], f["aula_sort"]),
            "docente": lambda f: (f["docente_sort"], f["fecha_sort"], f["hora_sort"]),
            "curso": lambda f: (f["curso"], f["fecha_sort"], f["hora_sort"]),
            "seccion": lambda f: (f["aula_sort"], f["fecha_sort"], f["hora_sort"]),
            "estado": lambda f: (f["estado_sort"], f["fecha_sort"], f["hora_sort"]),
        }
        filas.sort(key=claves_orden[campo_orden], reverse=reverso)

    return render(
        request,
        "asistencia/reporte_asistencia.html",
        {
            "promociones": Promocion.objects.all(),
            "promocion": promocion,
            "periodos": PeriodoAcademico.objects.filter(promocion=promocion) if promocion else [],
            "periodo": periodo,
            "docentes": Docente.objects.filter(estado="ACTIVO").order_by("apellidos_nombres"),
            "docente_id": docente_id,
            "cursos_filtro": cursos_filtro,
            "curso_id": curso_id,
            "fecha_desde": fecha_desde_str or "",
            "fecha_hasta": fecha_hasta_str or "",
            "solo_descuento": solo_descuento,
            "estado_filtro": estado_filtro,
            "filas": filas,
            "resumen": resumen,
            "campo_orden": campo_orden,
            "reverso": reverso,
            "next_orden": next_orden,
            "base_qs": base_qs,
            "volver_qs": request.GET.urlencode(),
            "estado_choices": AsistenciaResuelta.Estado.choices,
        },
    )


def _url_de_vuelta(request):
    """A dónde volver tras una corrección inline: acepta un path+query local
    completo (volver_url, usado por el calendario) o, si no viene, arma la URL
    del reporte con el query string que traía (volver_qs, comportamiento
    anterior)."""
    volver_url = request.POST.get("volver_url", "")
    if volver_url and url_has_allowed_host_and_scheme(
        volver_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return volver_url

    volver_qs = request.POST.get("volver_qs", "")
    url = reverse("controldocentes:reporte_asistencia")
    if volver_qs:
        url = f"{url}?{volver_qs}"
    return url


@login_required
def corregir_asistencia(request, pk):
    """Corrección manual inline, disparada desde la propia grilla del reporte
    (sin salir a otra pantalla): permite ajustar hora de entrada/salida y el
    estado final, y marcar el caso como resuelto."""
    if request.method != "POST":
        return redirect("controldocentes:reporte_asistencia")

    ar = get_object_or_404(AsistenciaResuelta, pk=pk)

    def _marcacion_manual(actual, hora_str, tipo):
        if not hora_str:
            return actual
        hora = datetime.strptime(hora_str, "%H:%M").time()
        ts = timezone.make_aware(datetime.combine(ar.fecha, hora))
        if actual is not None and actual.origen_dispositivo == "MANUAL":
            actual.timestamp = ts
            actual.save(update_fields=["timestamp"])
            return actual
        return MarcacionBiometrica.objects.create(
            id_biometrico=ar.docente.id_biometrico,
            timestamp=ts,
            tipo=tipo,
            origen_dispositivo="MANUAL",
        )

    ar.marcacion_entrada = _marcacion_manual(
        ar.marcacion_entrada, request.POST.get("hora_entrada"), MarcacionBiometrica.Tipo.ENTRADA
    )
    ar.marcacion_salida = _marcacion_manual(
        ar.marcacion_salida, request.POST.get("hora_salida"), MarcacionBiometrica.Tipo.SALIDA
    )

    nuevo_estado = request.POST.get("estado")
    if nuevo_estado in AsistenciaResuelta.Estado.values:
        ar.estado = nuevo_estado
        ar.corregido_manualmente = True

    ar.requiere_revision = request.POST.get("requiere_revision") == "on"
    ar.save()

    registrar_actividad(
        request,
        "Corrección de asistencia",
        detalle=f"{ar.docente} — {ar.fecha} — estado: {ar.get_estado_display()}",
    )

    return redirect(f"{_url_de_vuelta(request)}#fila-{ar.id}")


@login_required
def corregir_asistencia_lote(request):
    """Aplica una acción a varias filas 'por revisar' del reporte a la vez —
    para no tener que abrir el formulario de una en una cuando hay muchas."""
    if request.method != "POST":
        return redirect("controldocentes:reporte_asistencia")

    ids = request.POST.getlist("seleccion")
    accion = request.POST.get("accion_lote")

    if ids:
        registros = AsistenciaResuelta.objects.filter(pk__in=ids)
        if accion == "marcar_resuelto":
            registros.update(requiere_revision=False)
            registrar_actividad(request, "Corrección en lote", detalle=f"marcar_resuelto — {len(ids)} fila(s)")
        elif accion == "cambiar_estado":
            estado_lote = request.POST.get("estado_lote")
            if estado_lote in AsistenciaResuelta.Estado.values:
                registros.update(
                    estado=estado_lote, requiere_revision=False, corregido_manualmente=True
                )
                registrar_actividad(
                    request,
                    "Corrección en lote",
                    detalle=f"estado: {estado_lote} — {len(ids)} fila(s)",
                )

    return redirect(_url_de_vuelta(request))


_COLOR_ESTADO = {
    AsistenciaResuelta.Estado.PUNTUAL: "cal-verde",
    AsistenciaResuelta.Estado.TARDANZA: "cal-amarillo",
    AsistenciaResuelta.Estado.SOLO_ENTRADA: "cal-amarillo",
    AsistenciaResuelta.Estado.SOLO_SALIDA: "cal-amarillo",
    AsistenciaResuelta.Estado.AMBIGUO: "cal-amarillo",
    AsistenciaResuelta.Estado.NO_PROGRAMADO: "cal-amarillo",
    AsistenciaResuelta.Estado.FALTA: "cal-rojo",
    AsistenciaResuelta.Estado.RECUPERACION: "cal-verde",
}

MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


@login_required
def calendario_asistencia(request):
    """Vista experimental (aparte del reporte principal): calendario día por día
    por curso/sección, con la hora programada y el color de cumplimiento —
    igual a la planilla física que usa la escuela, pero con los datos reales
    del biométrico."""
    promocion_id = request.GET.get("promocion")
    periodo_id = request.GET.get("periodo")
    especialidad_id = request.GET.get("especialidad")
    curso_id = request.GET.get("curso")
    dia_id = request.GET.get("dia")
    dia_semana = int(dia_id) if dia_id and dia_id.isdigit() else None

    promocion = get_object_or_404(Promocion, pk=promocion_id) if promocion_id else None
    periodo = (
        PeriodoAcademico.objects.filter(pk=periodo_id, promocion=promocion).first()
        if periodo_id and promocion
        else None
    )
    if promocion and not periodo:
        periodos_promocion = PeriodoAcademico.objects.filter(promocion=promocion)
        if periodos_promocion.count() == 1:
            periodo = periodos_promocion.first()

    especialidades = _especialidades_de(promocion) if promocion else Especialidad.objects.none()
    especialidad = get_object_or_404(Especialidad, pk=especialidad_id) if especialidad_id else None
    grupo_listo = bool(periodo)

    hoy = timezone.localdate()
    fecha_desde_str = request.GET.get("fecha_desde")
    fecha_hasta_str = request.GET.get("fecha_hasta")
    fecha_desde = (
        datetime.strptime(fecha_desde_str, "%Y-%m-%d").date()
        if fecha_desde_str
        else hoy - timedelta(days=hoy.weekday())
    )
    fecha_hasta = (
        datetime.strptime(fecha_hasta_str, "%Y-%m-%d").date()
        if fecha_hasta_str
        else fecha_desde + timedelta(days=13)
    )
    if fecha_hasta < fecha_desde:
        fecha_hasta = fecha_desde
    if (fecha_hasta - fecha_desde).days > 60:
        fecha_hasta = fecha_desde + timedelta(days=60)

    grupos_curso = []
    columnas_fecha = []
    meses_header = []
    cursos_grupo = []
    volver_url_calendario = request.get_full_path()
    qs_sin_dia = request.GET.copy()
    qs_sin_dia.pop("dia", None)
    base_qs_calendario = qs_sin_dia.urlencode()

    if grupo_listo:
        # Grupos a combinar: si eligieron una especialidad, solo ese; si no,
        # TODOS los grupos de la promoción (las 2 especialidades, o "sin
        # especialidad" en períodos I/II donde todavía no se dividen).
        if especialidad:
            grupos = [especialidad]
        elif especialidades:
            grupos = list(especialidades)
        else:
            grupos = [None]

        todas_las_fechas = []
        f = fecha_desde
        while f <= fecha_hasta:
            if dia_semana is None or f.isoweekday() == dia_semana:
                todas_las_fechas.append(f)
            f += timedelta(days=1)

        feriados = set(
            Feriado.objects.filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta).values_list("fecha", flat=True)
        )

        cursos_vistos = {}
        set_columnas = set()
        datos_por_grupo = []

        for grupo_esp in grupos:
            ofertas_todas = (
                _ofertas_disponibles(periodo, grupo_esp).select_related("curso").order_by("curso__nombre")
            )
            for o in ofertas_todas:
                cursos_vistos[o.curso_id] = o.curso
            ofertas = ofertas_todas.filter(curso_id=curso_id) if curso_id else ofertas_todas
            aulas_grupo = list(_aulas_del_grupo(promocion, grupo_esp).order_by("numero"))
            ofertas_ids = list(ofertas.values_list("id", flat=True))
            if not ofertas_ids:
                continue

            bloques_qs = BloqueHorario.objects.filter(oferta_curso_id__in=ofertas_ids).select_related(
                "hora_pedagogica_inicio", "hora_pedagogica_fin"
            )
            if dia_semana is not None:
                # Con un día elegido, la hora mostrada y el orden deben ser los
                # de ESE día — un curso puede tener horas distintas otro día.
                bloques_qs = bloques_qs.filter(dia_semana=dia_semana)

            bloques_por_oferta = {}
            for b in bloques_qs:
                info = bloques_por_oferta.setdefault(b.oferta_curso_id, {"dias": set(), "ini": None, "fin": None})
                info["dias"].add(b.dia_semana)
                if info["ini"] is None or b.hora_pedagogica_inicio.numero_bloque < info["ini"][0]:
                    info["ini"] = (b.hora_pedagogica_inicio.numero_bloque, b.hora_pedagogica_inicio.hora_inicio)
                if info["fin"] is None or b.hora_pedagogica_fin.numero_bloque > info["fin"][0]:
                    info["fin"] = (b.hora_pedagogica_fin.numero_bloque, b.hora_pedagogica_fin.hora_fin)

            for info in bloques_por_oferta.values():
                for fecha in todas_las_fechas:
                    if fecha.isoweekday() in info["dias"]:
                        set_columnas.add(fecha)

            asignaciones = {
                (a.oferta_curso_id, a.aula_id): a
                for a in Asignacion.objects.filter(
                    oferta_curso_id__in=ofertas_ids, aula__in=aulas_grupo
                ).select_related("docente", "aula")
            }
            asignacion_ids = [a.id for a in asignaciones.values()]
            registros = {
                (r.asignacion_id, r.fecha): r
                for r in AsistenciaResuelta.objects.filter(
                    asignacion_id__in=asignacion_ids, fecha__gte=fecha_desde, fecha__lte=fecha_hasta
                ).select_related("marcacion_entrada", "marcacion_salida")
            }
            datos_por_grupo.append((ofertas, aulas_grupo, bloques_por_oferta, asignaciones, registros))

        cursos_grupo = sorted(cursos_vistos.values(), key=lambda c: c.nombre)
        columnas_fecha = sorted(set_columnas)

        for fecha in columnas_fecha:
            etiqueta = f"{MESES_ES[fecha.month]} {fecha.year}"
            if meses_header and meses_header[-1]["nombre"] == etiqueta:
                meses_header[-1]["colspan"] += 1
            else:
                meses_header.append({"nombre": etiqueta, "colspan": 1})

        # Un curso "común" (sin especialidad propia) aparece igual en las
        # ofertas de ambos grupos — hay que fusionarlo en UNA sola fila de
        # curso con todas las secciones juntas, no repetirlo por grupo.
        grupos_por_oferta = {}
        for ofertas, aulas_grupo, bloques_por_oferta, asignaciones, registros in datos_por_grupo:
            for oferta in ofertas:
                info = bloques_por_oferta.get(oferta.id)
                if not info:
                    continue
                entrada = grupos_por_oferta.setdefault(
                    oferta.id,
                    {
                        "curso": oferta.curso.nombre,
                        "hora_ini": info["ini"][1] if info["ini"] else None,
                        "hora_fin": info["fin"][1] if info["fin"] else None,
                        "hora_orden": info["ini"][0] if info["ini"] else 999,
                        "filas": [],
                    },
                )
                for aula in aulas_grupo:
                    asignacion = asignaciones.get((oferta.id, aula.id))
                    if not asignacion:
                        continue
                    celdas = []
                    for fecha in columnas_fecha:
                        if fecha.isoweekday() not in info["dias"]:
                            celdas.append({"aplica": False})
                            continue
                        if fecha in feriados:
                            celdas.append({"aplica": True, "feriado": True})
                            continue
                        r = registros.get((asignacion.id, fecha))
                        celdas.append(
                            {
                                "aplica": True,
                                "feriado": False,
                                "registro": r,
                                "color": _COLOR_ESTADO.get(r.estado, "cal-gris") if r else "cal-gris",
                                "hora_entrada": timezone.localtime(r.marcacion_entrada.timestamp) if r and r.marcacion_entrada else None,
                                "hora_salida": timezone.localtime(r.marcacion_salida.timestamp) if r and r.marcacion_salida else None,
                            }
                        )
                    entrada["filas"].append(
                        {
                            "aula": aula.codigo,
                            "aula_numero": aula.numero,
                            "docente": asignacion.docente,
                            "celdas": celdas,
                        }
                    )

        for entrada in grupos_por_oferta.values():
            if entrada["filas"]:
                entrada["filas"].sort(key=lambda f: f["aula_numero"])
                grupos_curso.append(entrada)

        grupos_curso.sort(key=lambda g: (g["hora_orden"], g["curso"]))

    return render(
        request,
        "asistencia/calendario_asistencia.html",
        {
            "promociones": Promocion.objects.all(),
            "promocion": promocion,
            "periodos": PeriodoAcademico.objects.filter(promocion=promocion) if promocion else [],
            "periodo": periodo,
            "especialidades": especialidades,
            "especialidad": especialidad,
            "dias_semana": DIAS[:6] if (periodo and periodo.usa_sabado) else DIAS[:5],
            "dia_semana": dia_semana,
            "base_qs_calendario": base_qs_calendario,
            "volver_url": volver_url_calendario,
            "estado_choices": AsistenciaResuelta.Estado.choices,
            "grupo_listo": grupo_listo,
            "cursos_grupo": cursos_grupo,
            "curso_id": curso_id,
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "meses_header": meses_header,
            "columnas_fecha": columnas_fecha,
            "grupos_curso": grupos_curso,
        },
    )


def _categoria_docente(grado):
    """PNP en actividad / PNP en retiro (r) / civil — según el texto del grado."""
    g = (grado or "").upper()
    if "PNP" not in g:
        return "CIVIL"
    if re.search(r"\(R\)|\bR\b", g):
        return "PNP_R"
    return "PNP"


@login_required
def cuadro_inasistencia(request):
    """Cuadro de inasistencia oficial (como el que ya usa la escuela en papel):
    lista de FALTAS del período, separada en tres bloques — PNP en actividad,
    PNP en retiro, y personal civil — con horas pedagógicas descontadas."""
    promocion_id = request.GET.get("promocion")
    periodo_id = request.GET.get("periodo")

    promocion = get_object_or_404(Promocion, pk=promocion_id) if promocion_id else None
    periodo = (
        PeriodoAcademico.objects.filter(pk=periodo_id, promocion=promocion).first()
        if periodo_id and promocion
        else None
    )
    if promocion and not periodo:
        periodos_promocion = PeriodoAcademico.objects.filter(promocion=promocion)
        if periodos_promocion.count() == 1:
            periodo = periodos_promocion.first()

    fecha_desde_str = request.GET.get("fecha_desde")
    fecha_hasta_str = request.GET.get("fecha_hasta")
    fecha_desde = fecha_hasta = None
    if fecha_desde_str:
        fecha_desde = datetime.strptime(fecha_desde_str, "%Y-%m-%d").date()
    if fecha_hasta_str:
        fecha_hasta = datetime.strptime(fecha_hasta_str, "%Y-%m-%d").date()

    grupos = {"PNP": [], "PNP_R": [], "CIVIL": []}
    etiquetas_grupo = {
        "PNP": "Docentes PNP en actividad",
        "PNP_R": "Docentes PNP en retiro",
        "CIVIL": "Docentes civiles",
    }

    if periodo:
        registros = (
            AsistenciaResuelta.objects.filter(
                estado=AsistenciaResuelta.Estado.FALTA,
                asignacion__oferta_curso__periodo_academico=periodo,
            )
            .select_related("docente", "asignacion__oferta_curso__curso")
            .order_by("docente__apellidos_nombres", "fecha")
        )
        if fecha_desde:
            registros = registros.filter(fecha__gte=fecha_desde)
        if fecha_hasta:
            registros = registros.filter(fecha__lte=fecha_hasta)

        for r in registros:
            categoria = _categoria_docente(r.docente.grado)
            grupos[categoria].append(
                {
                    "grado": r.docente.grado or "—",
                    "nombre": r.docente.apellidos_nombres,
                    "asignatura": r.asignacion.oferta_curso.curso.nombre if r.asignacion else "—",
                    "fecha": r.fecha,
                    "horas": r.horas_pedagogicas_descontadas,
                }
            )

        for categoria in grupos:
            for i, fila in enumerate(grupos[categoria], start=1):
                fila["numero"] = i

    grupos_ordenados = [
        (etiquetas_grupo[c], grupos[c]) for c in ("PNP", "PNP_R", "CIVIL")
    ]

    return render(
        request,
        "asistencia/cuadro_inasistencia.html",
        {
            "promociones": Promocion.objects.all(),
            "promocion": promocion,
            "periodos": PeriodoAcademico.objects.filter(promocion=promocion) if promocion else [],
            "periodo": periodo,
            "fecha_desde": fecha_desde_str or "",
            "fecha_hasta": fecha_hasta_str or "",
            "grupos_ordenados": grupos_ordenados,
        },
    )


@login_required
def sincronizar_biometrico_vista(request):
    """Botón del panel: hace exactamente lo mismo que el comando
    'sync_biometrico' de consola — solo descarga marcaciones nuevas del
    equipo, no cierra ningún día ni calcula estados."""
    if request.method != "POST":
        return redirect("controldocentes:index")

    from .biometrico import sincronizar_biometrico

    resultado = sincronizar_biometrico()
    registrar_actividad(request, "Sincronización manual del biométrico", detalle=resultado["mensaje"])
    params = f"msg={quote(resultado['mensaje'])}" if resultado["ok"] else f"error={quote(resultado['mensaje'])}"
    return redirect(f"{reverse('controldocentes:index')}?{params}")


@login_required
def imprimir_ficha_curricular(request, pk):
    """Hoja para imprimir del expediente completo del postulante: Evaluación
    Curricular (Anexo 13), Capacidad Docente (Anexo 11) y Entrevista
    Personal (Anexo 12) — las tres etapas, cada una con su puntaje y su
    mínimo aprobatorio, no solo el currículum."""
    postulante = get_object_or_404(Postulante, pk=pk)
    bloques = [
        ("1", "Grados Académicos y Títulos Profesionales", postulante.puntaje_grados_titulos(), Postulante.maximo_bloque(1)),
        ("2", "Actualizaciones y Capacitaciones afines a la unidad didáctica", postulante.puntaje_capacitaciones(), Postulante.maximo_bloque(2)),
        ("3", "Participación en Eventos Científicos e Investigaciones", postulante.puntaje_eventos_investigacion(), Postulante.maximo_bloque(3)),
        ("4", "Otros programas de formación continua", postulante.puntaje_otros_programas(), Postulante.maximo_bloque(4)),
        ("5", "Experiencia Docente Universitaria", postulante.puntaje_experiencia_docente(), Postulante.maximo_bloque(5)),
        ("6", "Experiencia Profesional", postulante.puntaje_experiencia_profesional(), Postulante.maximo_bloque(6)),
    ]
    capacidad_docente = [
        ("Planificación y evaluación de sesiones", postulante.cd_planificacion),
        ("Dominio pedagógico", postulante.cd_dominio_pedagogico),
        ("Dominio técnico", postulante.cd_dominio_tecnico),
        ("Comunicación efectiva", postulante.cd_comunicacion),
        ("Uso de recursos tecnológicos", postulante.cd_recursos_tecnologicos),
    ]
    entrevista_personal = [
        ("Proceso de enseñanza-aprendizaje", postulante.ep_proceso_ensenanza),
        ("Desarrollo institucional", postulante.ep_desarrollo_institucional),
        ("Especialidad y experiencia", postulante.ep_especialidad_experiencia),
        ("Investigación e innovación", postulante.ep_investigacion_innovacion),
        ("Personalidad", postulante.ep_personalidad),
    ]
    return render(
        request,
        "asistencia/imprimir_ficha_curricular.html",
        {
            "postulante": postulante,
            "bloques": bloques,
            "capacidad_docente": capacidad_docente,
            "entrevista_personal": entrevista_personal,
            "maximo_curricular": Postulante.maximo_evaluacion_curricular(),
            "nombre_escuela_corto": NOMBRE_ESCUELA_CORTO,
            "nombre_escuela_largo": NOMBRE_ESCUELA_LARGO,
        },
    )


def buscar_postulante_por_dni(request):
    """Devuelve en JSON los datos del último registro de Postulante con ese
    DNI (si existe), para autocompletar el formulario y evitar que jefatura
    reescriba a mano los datos de alguien que ya postuló antes."""
    dni = (request.GET.get("dni") or "").strip()
    if not dni:
        return JsonResponse({"encontrado": False})
    anterior = Postulante.objects.filter(dni=dni).order_by("-id").first()
    if not anterior:
        return JsonResponse({"encontrado": False})
    return JsonResponse({
        "encontrado": True,
        "apellidos": anterior.apellidos,
        "nombres": anterior.nombres,
        "cip": anterior.cip,
        "celular": anterior.celular,
        "procedencia": anterior.procedencia,
        "grado": anterior.grado,
    })
