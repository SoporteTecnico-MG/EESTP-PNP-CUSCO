import hashlib

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from .models import (
    Asignacion,
    Aula,
    BloqueHorario,
    Curso,
    Docente,
    HoraPedagogica,
    OfertaCurso,
    PeriodoAcademico,
    Promocion,
)

DIAS = list(BloqueHorario.Dia.choices)


def home(request):
    """Página pública institucional: info de la EESTP + convocatorias (a llenar más
    adelante) + acceso a iniciar sesión. No requiere estar logueado."""
    return render(request, "asistencia/home.html")


@login_required
def post_login_redirect(request):
    """Después de iniciar sesión, cada rol va a lo suyo: administradores al control
    total (admin/Control Docentes), docentes y estudiantes al Aula Virtual."""
    user = request.user
    if user.is_staff or user.is_superuser:
        return redirect("/admin/")
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


def _curso_color(nombre):
    """Color pastel determinístico a partir del nombre del curso, para que el mismo
    curso siempre se vea del mismo color en toda la grilla (como en la hoja de referencia)."""
    h = int(hashlib.md5(nombre.encode("utf-8")).hexdigest(), 16)
    hue = h % 360
    return f"hsl({hue}, 55%, 82%)"


def _cursos_disponibles(aula):
    """Comunes + los propios de la especialidad del aula (si ya la tiene definida)."""
    q = Q(especialidad__isnull=True)
    if aula.especialidad_id:
        q |= Q(especialidad_id=aula.especialidad_id)
    return Curso.objects.filter(q).order_by("nombre")


def _ofertas_disponibles(aula, periodo):
    """Ofertas de curso de este período que le corresponden a esta aula por especialidad
    (comunes + las de su propia especialidad). El horario, si ya lo tienen, es compartido."""
    q = Q(curso__especialidad__isnull=True)
    if aula.especialidad_id:
        q |= Q(curso__especialidad_id=aula.especialidad_id)
    return OfertaCurso.objects.filter(q, periodo_academico=periodo).select_related("curso")


def _construir_grilla(aula, periodo=None):
    """Grilla semanal de una aula. Si se da `periodo`, incluye también los cursos que
    le corresponden pero todavía no tienen horario fijado (celdas 'libre', para poder
    programarlos) y los que ya tienen horario pero a esta aula le falta docente
    ('pendiente_docente'). Sin `periodo` (solo lectura), muestra nada más lo que esta
    aula ya tiene realmente asignado."""
    horas = list(HoraPedagogica.objects.all().order_by("numero_bloque"))
    horas_clase = [h for h in horas if h.tipo == "CLASE"]

    if periodo:
        ofertas_ids = list(_ofertas_disponibles(aula, periodo).values_list("id", flat=True))
    else:
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

    indice = {}
    ocupadas = set()
    for b in bloques:
        ini = b.hora_pedagogica_inicio.numero_bloque
        fin = b.hora_pedagogica_fin.numero_bloque
        asignacion = asignaciones_aula.get(b.oferta_curso_id)
        color = _curso_color(b.oferta_curso.curso.nombre)
        indice[(ini, b.dia_semana)] = {
            "bloque": b,
            "oferta": b.oferta_curso,
            "asignacion": asignacion,
            "rowspan": fin - ini + 1,
            "color": color,
        }
        for n in range(ini, fin + 1):
            ocupadas.add((n, b.dia_semana))

    filas_grilla = []
    for hp in horas:
        fila = {"hora": hp, "es_receso": hp.tipo != "CLASE", "celdas": []}
        if not fila["es_receso"]:
            for dia_num, dia_nombre in DIAS[:6]:  # Lunes a Sábado
                clave = (hp.numero_bloque, dia_num)
                if clave in indice:
                    info = indice[clave]
                    tipo = "inicio" if info["asignacion"] else "pendiente_docente"
                    fila["celdas"].append({"tipo": tipo, "dia": dia_num, **info})
                elif clave in ocupadas:
                    fila["celdas"].append({"tipo": "ocupada"})
                elif periodo:
                    # horas de fin posibles: desde esta hasta la siguiente ya ocupada (o el final del día)
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
                else:
                    fila["celdas"].append({"tipo": "libre_lectura"})
        filas_grilla.append(fila)

    return filas_grilla


@login_required
def asignar_horario(request):
    promocion_id = request.GET.get("promocion") or request.POST.get("promocion")
    periodo_id = request.GET.get("periodo") or request.POST.get("periodo")
    aula_id = request.GET.get("aula") or request.POST.get("aula")

    promocion = get_object_or_404(Promocion, pk=promocion_id) if promocion_id else None
    periodo = get_object_or_404(PeriodoAcademico, pk=periodo_id, promocion=promocion) if periodo_id else None
    aula = get_object_or_404(Aula, pk=aula_id, promocion=promocion) if aula_id else None

    # Si la promoción tiene un solo período, no hacer que el usuario lo elija aparte.
    if promocion and not periodo:
        periodos_promocion = PeriodoAcademico.objects.filter(promocion=promocion)
        if periodos_promocion.count() == 1:
            periodo = periodos_promocion.first()

    mensaje = None
    error = None

    if request.method == "POST" and aula and periodo:
        accion = request.POST.get("accion")

        if accion == "programar_curso":
            # El docente ya se elige aparte (ficha del docente). Aquí solo se fija el
            # horario de un curso que esta aula YA tiene con docente asignado y que
            # todavía no tiene horario — se fija una sola vez por período.
            curso_id = request.POST.get("curso")
            dia = request.POST.get("dia_semana")
            hp_ini_id = request.POST.get("hora_pedagogica_inicio")
            hp_fin_id = request.POST.get("hora_pedagogica_fin")

            asignacion_existente = Asignacion.objects.filter(
                aula=aula, oferta_curso__curso_id=curso_id, oferta_curso__periodo_academico=periodo
            ).select_related("oferta_curso").first()

            if not (curso_id and dia and hp_ini_id and hp_fin_id):
                error = "Faltan datos para programar el curso."
            elif not asignacion_existente:
                error = "Ese curso todavía no tiene docente asignado en esta aula — asígnalo primero desde la ficha del docente."
            elif BloqueHorario.objects.filter(oferta_curso=asignacion_existente.oferta_curso).exists():
                error = "Ese curso ya tiene horario fijado para este período."
            else:
                oferta = asignacion_existente.oferta_curso
                hp_ini = get_object_or_404(HoraPedagogica, pk=hp_ini_id)
                hp_fin = get_object_or_404(HoraPedagogica, pk=hp_fin_id)
                ofertas_aula_ids = _ofertas_disponibles(aula, periodo).values_list("id", flat=True)
                solapa = BloqueHorario.objects.filter(
                    oferta_curso_id__in=ofertas_aula_ids,
                    dia_semana=dia,
                    hora_pedagogica_inicio__numero_bloque__lte=hp_fin.numero_bloque,
                    hora_pedagogica_fin__numero_bloque__gte=hp_ini.numero_bloque,
                ).exists()
                if solapa:
                    error = "Ese horario se cruza con un curso que ya tiene esta aula a esa hora."
                else:
                    BloqueHorario.objects.create(
                        oferta_curso=oferta,
                        dia_semana=dia,
                        hora_pedagogica_inicio=hp_ini,
                        hora_pedagogica_fin=hp_fin,
                    )
                    mensaje = f"{oferta.curso.nombre} programado — este horario ya queda fijo para todas las aulas."

        elif accion == "asignar_docente":
            # Curso que YA tiene horario fijado (puesto por esta u otra aula); solo falta el docente.
            oferta_id = request.POST.get("oferta_curso")
            docente_id = request.POST.get("docente")
            oferta = _ofertas_disponibles(aula, periodo).filter(pk=oferta_id).first()
            if not oferta or not docente_id:
                error = "Faltan datos para asignar el docente."
            else:
                Asignacion.objects.update_or_create(
                    aula=aula, oferta_curso=oferta, defaults={"docente_id": docente_id}
                )
                mensaje = f"Docente asignado para {oferta.curso.nombre}."

        elif accion == "quitar_docente":
            # Solo quita a ESTA aula del curso; el horario compartido sigue intacto
            # para las demás aulas que también lo dicten.
            asignacion_id = request.POST.get("asignacion_id")
            Asignacion.objects.filter(pk=asignacion_id, aula=aula).delete()
            mensaje = "Docente quitado de esta aula."

        params = f"promocion={promocion.id}&periodo={periodo.id}&aula={aula.id}"
        if mensaje:
            params += f"&msg={mensaje}"
        if error:
            params += f"&error={error}"
        return redirect(f"{request.path}?{params}")

    grilla = _construir_grilla(aula, periodo) if aula else None

    return render(
        request,
        "asistencia/asignar_horario.html",
        {
            "promociones": Promocion.objects.all(),
            "promocion": promocion,
            "periodos": PeriodoAcademico.objects.filter(promocion=promocion) if promocion else [],
            "periodo": periodo,
            "aulas": Aula.objects.filter(promocion=promocion) if promocion else [],
            "aula": aula,
            "grilla": grilla,
            "dias": DIAS[:6],
            "cursos_sin_horario": (
                Asignacion.objects.filter(
                    aula=aula,
                    oferta_curso__periodo_academico=periodo,
                    oferta_curso__bloques__isnull=True,
                )
                .select_related("oferta_curso__curso", "docente")
                .order_by("oferta_curso__curso__nombre")
                if aula and periodo
                else []
            ),
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

    grilla = _construir_grilla(aula) if aula else None

    return render(
        request,
        "asistencia/ver_horario.html",
        {
            "promociones": Promocion.objects.all(),
            "promocion": promocion,
            "aulas": Aula.objects.filter(promocion=promocion) if promocion else [],
            "aula": aula,
            "dias": DIAS[:6],
            "grilla": grilla,
        },
    )
