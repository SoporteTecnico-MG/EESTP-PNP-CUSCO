from urllib.parse import urlencode

from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html
from . import models
from . import views as asistencia_views

# El panel de /admin/ mezclaba dos procesos que no tienen nada que ver entre
# sí (control de asistencia de docentes ya contratados, y calificación de
# postulantes para contratar nuevos) bajo una sola URL y un solo menú. Ahora
# son dos AdminSite aparte, cada uno con su propia URL, título y dashboard —
# /admin/ queda como un pequeño "hub" que solo enlaza a los dos sectores.
control_docentes_site = admin.AdminSite(name="controldocentes")
proceso_docente_site = admin.AdminSite(name="procesodocente")

admin.site.site_header = "EESTP PNP CUSCO — Sistema Institucional"
admin.site.site_title = "Sistema Institucional"
admin.site.index_title = "Elige un sector"
admin.site.index_template = "admin/hub_index.html"

control_docentes_site.site_header = "EESTP PNP CUSCO — Control Docentes"
control_docentes_site.site_title = "Control Docentes"
control_docentes_site.index_title = "Panel de Control Docentes"

proceso_docente_site.site_header = "EESTP PNP CUSCO — Proceso Docente"
proceso_docente_site.site_title = "Proceso Docente"
proceso_docente_site.index_title = "Calificación y selección de postulantes"


def _login_unificado(request, extra_context=None):
    """El admin de Django trae su propia pantalla de login (/admin/login/),
    aparte de la pública que ya diseñamos (/login/) — esto la reemplaza para
    que todo el sistema (los 3 sitios de admin) use una sola pantalla de
    inicio de sesión."""
    next_url = request.GET.get("next") or reverse("admin:index")
    return redirect(f"{reverse('asistencia:login')}?{urlencode({'next': next_url})}")


admin.site.login = _login_unificado
control_docentes_site.login = _login_unificado
proceso_docente_site.login = _login_unificado

_control_docentes_get_app_list = control_docentes_site.get_app_list


_SECCIONES_CONTROL_DOCENTES = [
    ("control-docentes", "Control Docentes", [
        "Docente", "Promocion", "Especialidad", "Aula", "PeriodoAcademico",
        "Curso", "OfertaCurso", "HoraPedagogica", "Asignacion", "BloqueHorario",
        "Feriado",
    ]),
    ("asistencia-biometrica", "Asistencia Biométrica", [
        "MarcacionBiometrica", "AsistenciaResuelta",
    ]),
    ("registro-actividad", "Registro de Actividad", [
        "RegistroActividad",
    ]),
]


def _get_app_list_control_docentes(request, app_label=None):
    """El panel mezclaba TODO (docentes, horarios, marcaciones, bitácora) en
    una sola lista alfabética dentro de "Asistencia" — son procesos
    distintos con audiencias distintas (Registro de Actividad es solo del
    administrador general), así que se separan en secciones propias del
    panel en vez de una sola bolsa revuelta."""
    app_list = _control_docentes_get_app_list(request, app_label)
    if app_label is not None:
        return app_list

    asistencia_app = next((a for a in app_list if a["app_label"] == "asistencia"), None)
    if asistencia_app is None:
        return app_list

    modelos_por_nombre = {m["object_name"]: m for m in asistencia_app["models"]}
    secciones_nuevas = []
    for slug, nombre, nombres_modelo in _SECCIONES_CONTROL_DOCENTES:
        modelos_seccion = [
            modelos_por_nombre.pop(nombre_modelo)
            for nombre_modelo in nombres_modelo
            if nombre_modelo in modelos_por_nombre
        ]
        if modelos_seccion:
            secciones_nuevas.append({
                "name": nombre,
                "app_label": slug,
                "app_url": asistencia_app["app_url"],
                "has_module_perms": asistencia_app["has_module_perms"],
                "models": modelos_seccion,
            })

    # Cualquier modelo nuevo que no esté todavía en la lista de arriba se
    # queda visible en "Asistencia" en vez de desaparecer silenciosamente.
    indice = app_list.index(asistencia_app)
    sobrantes = list(modelos_por_nombre.values())
    if sobrantes:
        asistencia_app["models"] = sobrantes
        return app_list[:indice + 1] + secciones_nuevas + app_list[indice + 1:]
    return app_list[:indice] + secciones_nuevas + app_list[indice + 1:]


control_docentes_site.get_app_list = _get_app_list_control_docentes

_control_docentes_index = control_docentes_site.index


def _index_control_docentes(request, extra_context=None):
    from django.utils import timezone

    extra_context = extra_context or {}
    extra_context.update(
        {
            "stat_docentes": models.Docente.objects.filter(estado="ACTIVO").count(),
            "stat_promociones": models.Promocion.objects.filter(estado="ACTIVA").count(),
            "stat_aulas": models.Aula.objects.count(),
            "stat_asignaciones_sin_horario": models.Asignacion.objects.filter(
                oferta_curso__bloques__isnull=True
            ).distinct().count(),
            "stat_marcaciones_hoy": models.MarcacionBiometrica.objects.filter(
                timestamp__date=timezone.localdate()
            ).count(),
            "stat_requieren_revision": models.AsistenciaResuelta.objects.filter(
                requiere_revision=True
            ).count(),
            "mensaje": request.GET.get("msg"),
            "error": request.GET.get("error"),
        }
    )
    return _control_docentes_index(request, extra_context)


control_docentes_site.index = _index_control_docentes
control_docentes_site.index_template = "admin/controldocentes_index.html"

_proceso_docente_index = proceso_docente_site.index


def _index_proceso_docente(request, extra_context=None):
    extra_context = extra_context or {}
    postulantes = models.Postulante.objects.all()
    extra_context.update(
        {
            "stat_postulantes": postulantes.count(),
            "stat_convocatorias": postulantes.values("convocatoria").distinct().count(),
            "stat_ganadores": sum(1 for p in postulantes if p.resultado().startswith("GANADOR")),
            "stat_vinculados": postulantes.filter(docente__isnull=False).count(),
        }
    )
    return _proceso_docente_index(request, extra_context)


proceso_docente_site.index = _index_proceso_docente
proceso_docente_site.index_template = "admin/procesodocente_index.html"

_proceso_docente_get_app_list = proceso_docente_site.get_app_list

_SECCIONES_PROCESO_DOCENTE = [
    ("convocatorias", "Convocatorias", ["Postulante", "Convocatoria"]),
    ("consulta-docentes", "Consulta de Docentes", ["Docente"]),
]


def _get_app_list_proceso_docente(request, app_label=None):
    """Postulante y Docente quedan bajo la misma app de Python ('asistencia'),
    así que sin esto Django los mostraría juntos como una sola sección
    "Asistencia" — se separan para que quede claro que Docente aquí es solo
    de consulta (para vincular), no el catálogo principal."""
    app_list = _proceso_docente_get_app_list(request, app_label)
    if app_label is not None:
        return app_list

    asistencia_app = next((a for a in app_list if a["app_label"] == "asistencia"), None)
    if asistencia_app is None:
        return app_list

    modelos_por_nombre = {m["object_name"]: m for m in asistencia_app["models"]}
    secciones_nuevas = []
    for slug, nombre, nombres_modelo in _SECCIONES_PROCESO_DOCENTE:
        modelos_seccion = [
            modelos_por_nombre.pop(nombre_modelo)
            for nombre_modelo in nombres_modelo
            if nombre_modelo in modelos_por_nombre
        ]
        if modelos_seccion:
            secciones_nuevas.append({
                "name": nombre,
                "app_label": slug,
                "app_url": asistencia_app["app_url"],
                "has_module_perms": asistencia_app["has_module_perms"],
                "models": modelos_seccion,
            })

    indice = app_list.index(asistencia_app)
    sobrantes = list(modelos_por_nombre.values())
    if sobrantes:
        asistencia_app["models"] = sobrantes
        return app_list[:indice + 1] + secciones_nuevas + app_list[indice + 1:]
    return app_list[:indice] + secciones_nuevas + app_list[indice + 1:]


proceso_docente_site.get_app_list = _get_app_list_proceso_docente

_proceso_docente_get_urls = proceso_docente_site.get_urls


def _get_urls_proceso_docente():
    custom = [
        path(
            "imprimir-ficha-curricular/<int:pk>/",
            proceso_docente_site.admin_view(asistencia_views.imprimir_ficha_curricular),
            name="imprimir_ficha_curricular",
        ),
    ]
    return custom + _proceso_docente_get_urls()


proceso_docente_site.get_urls = _get_urls_proceso_docente

_control_docentes_get_urls = control_docentes_site.get_urls


def _get_urls():
    custom = [
        path(
            "armar-horario/",
            control_docentes_site.admin_view(asistencia_views.asignar_horario),
            name="armar_horario",
        ),
        path(
            "ver-horario/",
            control_docentes_site.admin_view(asistencia_views.ver_horario),
            name="ver_horario",
        ),
        path(
            "reporte-asistencia/",
            control_docentes_site.admin_view(asistencia_views.reporte_asistencia),
            name="reporte_asistencia",
        ),
        path(
            "corregir-asistencia/<int:pk>/",
            control_docentes_site.admin_view(asistencia_views.corregir_asistencia),
            name="corregir_asistencia",
        ),
        path(
            "corregir-asistencia-lote/",
            control_docentes_site.admin_view(asistencia_views.corregir_asistencia_lote),
            name="corregir_asistencia_lote",
        ),
        path(
            "calendario-asistencia/",
            control_docentes_site.admin_view(asistencia_views.calendario_asistencia),
            name="calendario_asistencia",
        ),
        path(
            "cuadro-inasistencia/",
            control_docentes_site.admin_view(asistencia_views.cuadro_inasistencia),
            name="cuadro_inasistencia",
        ),
        path(
            "sincronizar-biometrico/",
            control_docentes_site.admin_view(asistencia_views.sincronizar_biometrico_vista),
            name="sincronizar_biometrico",
        ),
    ]
    return custom + _control_docentes_get_urls()


control_docentes_site.get_urls = _get_urls


@admin.register(models.Especialidad, site=control_docentes_site)
class EspecialidadAdmin(admin.ModelAdmin):
    list_display = ("nombre",)
    search_fields = ("nombre",)


class _PeriodoSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            periodo = models.PeriodoAcademico.objects.filter(pk=value.value).select_related("promocion").first()
            if periodo:
                option["attrs"]["data-promocion"] = str(periodo.promocion_id)
        return option


class _AulaSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            aula = models.Aula.objects.filter(pk=value.value).only("promocion_id", "especialidad_id").first()
            if aula:
                option["attrs"]["data-promocion"] = str(aula.promocion_id)
                option["attrs"]["data-especialidad"] = str(aula.especialidad_id or "")
        return option


class _OfertaCursoSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            oferta = models.OfertaCurso.objects.filter(pk=value.value).select_related(
                "periodo_academico", "curso"
            ).first()
            if oferta:
                option["attrs"]["data-periodo"] = str(oferta.periodo_academico_id)
                option["attrs"]["data-promocion"] = str(oferta.periodo_academico.promocion_id)
                option["attrs"]["data-especialidad"] = str(oferta.curso.especialidad_id or "")
        return option


class AsignacionInlineForm(forms.ModelForm):
    """Promoción → Período → Aula → Curso, en cascada. El horario (día/hora) NO se
    elige aquí: se programa una sola vez por período en 'Ofertas de Curso', porque
    es el mismo para todas las aulas/secciones que dicten ese curso."""

    promocion_filtro = forms.ModelChoiceField(
        queryset=models.Promocion.objects.all(),
        required=False,
        label="Promoción",
        widget=forms.Select(attrs={"data-role": "promocion-filtro"}),
    )
    periodo_filtro = forms.ModelChoiceField(
        queryset=models.PeriodoAcademico.objects.all(),
        required=False,
        label="Período",
        widget=_PeriodoSelect(attrs={"data-role": "periodo-filtro"}),
    )

    class Meta:
        model = models.Asignacion
        fields = ("promocion_filtro", "periodo_filtro", "aula", "oferta_curso")
        widgets = {
            "aula": _AulaSelect(attrs={"data-role": "aula-select"}),
            "oferta_curso": _OfertaCursoSelect(attrs={"data-role": "oferta-select"}),
        }

    class Media:
        js = ("asistencia/admin_cascada.js",)


class AsignacionInline(admin.StackedInline):
    """Cascada Promoción → Período → Aula → Curso, directo en la ficha del docente,
    sin salir a otra pantalla. El filtrado (incluida la especialidad del aula) lo
    hace admin_cascada.js. El horario se programa aparte, una vez por período,
    en Ofertas de Curso (es el mismo para todas las aulas)."""

    model = models.Asignacion
    form = AsignacionInlineForm
    extra = 1
    classes = ("collapse",)
    fields = ("promocion_filtro", "periodo_filtro", "aula", "oferta_curso")


@admin.register(models.Docente, site=control_docentes_site)
class DocenteAdmin(admin.ModelAdmin):
    list_display = ("dni", "apellidos_nombres", "grado", "celular", "id_biometrico", "estado")
    list_filter = ("estado", "grado")
    search_fields = ("dni", "apellidos_nombres", "id_biometrico")
    ordering = ("apellidos_nombres",)
    inlines = [AsignacionInline]


# El autocomplete_fields="docente" de PostulanteAdmin (sitio Proceso Docente)
# necesita que Docente esté registrado también en ESE sitio — si no, Django
# rechaza el arranque (E039: no se puede autocompletar contra un modelo que
# no está en el mismo AdminSite). Sirve además para que, desde Proceso
# Docente, se pueda revisar el registro de un Docente sin cruzar de sitio.
proceso_docente_site.register(models.Docente, DocenteAdmin)


@admin.register(models.Promocion, site=control_docentes_site)
class PromocionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "anio_ingreso", "fecha_inicio_formacion", "estado")
    list_filter = ("estado", "anio_ingreso")
    search_fields = ("nombre",)
    ordering = ("-anio_ingreso", "nombre")


@admin.register(models.Aula, site=control_docentes_site)
class AulaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "promocion", "especialidad")
    list_filter = ("promocion", "especialidad")
    search_fields = ("numero", "promocion__nombre")
    ordering = ("promocion", "numero")


@admin.register(models.PeriodoAcademico, site=control_docentes_site)
class PeriodoAcademicoAdmin(admin.ModelAdmin):
    list_display = ("promocion", "numero_periodo", "nombre", "fecha_inicio", "fecha_fin", "estado", "usa_sabado")
    list_editable = ("usa_sabado",)
    list_filter = ("promocion", "estado")
    ordering = ("promocion", "numero_periodo")


@admin.register(models.Curso, site=control_docentes_site)
class CursoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "especialidad")
    list_filter = ("especialidad",)
    search_fields = ("nombre",)
    ordering = ("nombre",)


def _asignaciones_texto(oferta_curso):
    partes = [
        f"{a.aula.codigo}: {a.docente.apellidos_nombres}"
        for a in models.Asignacion.objects.filter(oferta_curso=oferta_curso).select_related("aula", "docente")
    ]
    return "; ".join(partes) if partes else "— sin docente asignado aún —"


class BloqueHorarioInline(admin.TabularInline):
    """El horario (día/hora) de un curso se define aquí, UNA sola vez por período —
    es el mismo para todas las aulas/secciones que lo dicten ese período."""

    model = models.BloqueHorario
    extra = 1
    fields = ("dia_semana", "hora_pedagogica_inicio", "hora_pedagogica_fin", "asignado_a")
    readonly_fields = ("asignado_a",)

    def asignado_a(self, obj):
        if not obj or not obj.pk:
            return "—"
        return _asignaciones_texto(obj.oferta_curso)

    asignado_a.short_description = "Aula: Docente"


@admin.register(models.OfertaCurso, site=control_docentes_site)
class OfertaCursoAdmin(admin.ModelAdmin):
    list_display = ("periodo_academico", "curso", "horas_pedagogicas")
    list_filter = ("periodo_academico",)
    search_fields = ("curso__nombre", "periodo_academico__promocion__nombre")
    ordering = ("periodo_academico", "curso")
    inlines = [BloqueHorarioInline]


@admin.register(models.HoraPedagogica, site=control_docentes_site)
class HoraPedagogicaAdmin(admin.ModelAdmin):
    list_display = ("numero_bloque", "hora_inicio", "hora_fin", "tipo")
    ordering = ("numero_bloque",)


@admin.register(models.Asignacion, site=control_docentes_site)
class AsignacionAdmin(admin.ModelAdmin):
    list_display = ("aula", "oferta_curso", "docente", "horas_pedagogicas_totales")
    list_filter = ("aula__promocion", "aula", "docente")
    search_fields = ("docente__apellidos_nombres", "docente__dni")
    ordering = ("aula", "oferta_curso")
    readonly_fields = ("horas_pedagogicas_totales", "enlace_ver_horario")

    fieldsets = (
        (None, {
            "fields": ("aula", "oferta_curso", "docente", "horas_pedagogicas_totales", "enlace_ver_horario"),
        }),
    )

    def enlace_ver_horario(self, obj):
        if not obj.pk:
            return "Guarda la asignación primero."
        url = f"{reverse('controldocentes:ver_horario')}?promocion={obj.aula.promocion_id}&aula={obj.aula_id}"
        return format_html(
            '<a class="button" href="{}" style="background:#1d5a43;color:#fff;padding:.4rem .8rem;'
            'border-radius:.3rem;text-decoration:none;display:inline-block">'
            'Ver horario visual de esta aula</a>',
            url,
        )

    enlace_ver_horario.short_description = "Horario visual"


@admin.register(models.BloqueHorario, site=control_docentes_site)
class BloqueHorarioAdmin(admin.ModelAdmin):
    """El listado plano de Django no sirve para esto: en vez de mostrarlo, 'Bloques
    de Horario' lleva directo a la grilla de Armar Horario — ahí es donde se fija
    el horario de un curso (con sus desplegables de promoción/período/aula) y se
    ve qué docente ya tiene asignado en cada bloque."""

    list_display = ("oferta_curso", "dia_semana", "hora_pedagogica_inicio", "hora_pedagogica_fin", "asignado_a")
    list_filter = ("dia_semana", "oferta_curso__periodo_academico")
    search_fields = ("oferta_curso__curso__nombre",)
    ordering = ("oferta_curso", "dia_semana", "hora_pedagogica_inicio")

    def changelist_view(self, request, extra_context=None):
        from django.shortcuts import redirect

        return redirect(reverse("controldocentes:armar_horario"))

    def asignado_a(self, obj):
        return _asignaciones_texto(obj.oferta_curso)

    asignado_a.short_description = "Aula: Docente"


@admin.register(models.MarcacionBiometrica, site=control_docentes_site)
class MarcacionBiometricaAdmin(admin.ModelAdmin):
    list_display = ("id_biometrico", "timestamp", "tipo", "origen_dispositivo", "importado_en")
    list_filter = ("tipo", "origen_dispositivo")
    search_fields = ("id_biometrico",)
    ordering = ("-timestamp",)
    date_hierarchy = "timestamp"


@admin.register(models.AsistenciaResuelta, site=control_docentes_site)
class AsistenciaResueltaAdmin(admin.ModelAdmin):
    """Editable y creable a mano (para cuando el biométrico falló, o para
    corregir un caso puntual) — no tiene readonly_fields a propósito."""

    list_display = (
        "docente",
        "fecha",
        "asignacion",
        "estado",
        "minutos_tardanza",
        "horas_pedagogicas_descontadas",
        "horas_efectivas",
        "salida_anticipada",
        "requiere_revision",
    )
    list_filter = ("estado", "requiere_revision", "salida_anticipada", "fecha")
    search_fields = ("docente__apellidos_nombres", "docente__dni")
    ordering = ("-fecha", "docente")
    date_hierarchy = "fecha"
    autocomplete_fields = ("docente", "asignacion", "marcacion_entrada", "marcacion_salida")


@admin.register(models.Feriado, site=control_docentes_site)
class FeriadoAdmin(admin.ModelAdmin):
    """Feriados nacionales y suspensiones por disposición superior. El motor de
    resolución (cerrar_dia) salta por completo estas fechas — no genera Falta."""

    list_display = ("fecha", "descripcion", "tipo")
    list_filter = ("tipo",)
    search_fields = ("descripcion",)
    ordering = ("-fecha",)
    date_hierarchy = "fecha"
    actions = ["limpiar_asistencias_de_estas_fechas"]

    @admin.action(description="Eliminar asistencias resueltas ya generadas en estas fechas")
    def limpiar_asistencias_de_estas_fechas(self, request, queryset):
        fechas = list(queryset.values_list("fecha", flat=True))
        borrados, _ = models.AsistenciaResuelta.objects.filter(fecha__in=fechas).delete()
        self.message_user(request, f"Se eliminaron {borrados} registro(s) de asistencia de esas fechas.")


@admin.register(models.RegistroActividad, site=control_docentes_site)
class RegistroActividadAdmin(admin.ModelAdmin):
    """Bitácora de acciones del sistema (login/logout, correcciones,
    sincronizaciones manuales). Solo el administrador general (superusuario)
    puede verla — para el resto de usuarios, ni siquiera aparece en el menú."""

    list_display = ("fecha_hora", "usuario", "accion", "detalle")
    list_filter = ("accion",)
    search_fields = ("usuario__username", "accion", "detalle")
    date_hierarchy = "fecha_hora"
    ordering = ("-fecha_hora",)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Convocatoria, site=proceso_docente_site)
class ConvocatoriaAdmin(admin.ModelAdmin):
    """Catálogo de convocatorias — se maneja aparte para que el campo
    "Convocatoria" del postulante sea un desplegable (son pocas) en vez de
    texto libre."""

    list_display = ("nombre", "fecha_inicio", "fecha_fin")
    search_fields = ("nombre",)
    ordering = ("-fecha_inicio", "nombre")


@admin.register(models.Postulante, site=proceso_docente_site)
class PostulanteAdmin(admin.ModelAdmin):
    """Calificación de postulantes a la docencia, según el Manual del
    Personal Docente de la ENFPP PNP (Anexos 10 a 13) — un campo por cada
    renglón de las tablas oficiales; el puntaje de cada bloque y el
    resultado final se calculan solos."""

    list_display = (
        "nombre_completo",
        "convocatoria",
        "unidad_didactica",
        "postula_a_otro_curso_misma_convocatoria",
        "col_curricular",
        "col_capacidad_docente",
        "col_entrevista",
        "col_puntaje_total",
        "col_resultado",
        "docente",
    )
    list_filter = ("convocatoria", "unidad_didactica", "procedencia")
    search_fields = ("apellidos", "nombres", "dni", "cip", "unidad_didactica__nombre")
    ordering = ("convocatoria", "unidad_didactica", "apellidos", "nombres")
    autocomplete_fields = ("docente",)
    actions = ["vincular_o_crear_docente_action"]

    @admin.display(description="Postulante", ordering="apellidos")
    def nombre_completo(self, obj):
        return obj.nombre_completo

    readonly_fields = (
        "vista_puntaje_grados_titulos",
        "vista_puntaje_capacitaciones",
        "vista_puntaje_eventos_investigacion",
        "vista_puntaje_otros_programas",
        "vista_puntaje_experiencia_docente",
        "vista_puntaje_experiencia_profesional",
        "vista_puntaje_evaluacion_curricular",
        "vista_imprimir_ficha",
        "vista_puntaje_capacidad_docente",
        "vista_puntaje_entrevista_personal",
        "vista_puntaje_total",
        "vista_resultado",
    )

    fieldsets = (
        ("Datos del postulante (Anexo 06)", {
            "fields": (
                "apellidos", "nombres", "dni", "cip", "celular", "grado", "procedencia",
                "unidad_didactica", "convocatoria", "postula_a_otro_curso_misma_convocatoria",
                "fecha_evaluacion", "docente",
            )
        }),
        ("1. Grados académicos y títulos profesionales (máx. 20)", {
            "fields": (
                "tiene_titulo_profesional", "tiene_titulo_profesional_tecnico",
                "tiene_maestria", "tiene_doctorado", "tiene_segunda_especialidad",
                "vista_puntaje_grados_titulos",
            )
        }),
        ("2. Actualizaciones y capacitaciones afines (máx. 3)", {
            "fields": (
                "diplomados_120h", "programas_16_96h_afines",
                "vista_puntaje_capacitaciones",
            )
        }),
        ("3. Participación en eventos científicos e investigación (máx. 3)", {
            "fields": (
                "ponente_eventos", "asistente_eventos", "investigaciones", "publicaciones",
                "vista_puntaje_eventos_investigacion",
            )
        }),
        ("4. Otros programas de formación continua (máx. 4)", {
            "fields": (
                "programas_96h_otros", "programas_16_96h_otros", "cursos_ofimatica_24h",
                "vista_puntaje_otros_programas",
            )
        }),
        ("5. Experiencia docente universitaria (máx. 4)", {
            "fields": (
                "pregrado_ciclos", "maestria_cursos",
                "vista_puntaje_experiencia_docente",
            )
        }),
        ("6. Experiencia profesional (máx. 6)", {
            "fields": ("experiencia_profesional_anios", "vista_puntaje_experiencia_profesional")
        }),
        ("Evaluación Curricular — total (máx. 40, mínimo aprobatorio 20)", {
            "fields": ("vista_puntaje_evaluacion_curricular", "vista_imprimir_ficha")
        }),
        ("Capacidad Docente — Anexo 11 (cada bloque de 0 a 7, máx. 35, mínimo aprobatorio 30)", {
            "fields": (
                "cd_planificacion", "cd_dominio_pedagogico", "cd_dominio_tecnico",
                "cd_comunicacion", "cd_recursos_tecnologicos",
                "vista_puntaje_capacidad_docente",
            )
        }),
        ("Entrevista Personal — Anexo 12 (cada bloque de 0 a 5, máx. 25, mínimo aprobatorio 10)", {
            "fields": (
                "ep_proceso_ensenanza", "ep_desarrollo_institucional", "ep_especialidad_experiencia",
                "ep_investigacion_innovacion", "ep_personalidad",
                "vista_puntaje_entrevista_personal",
            )
        }),
        ("Resultado final (mínimo aprobatorio 60 de 100)", {
            "fields": ("vista_puntaje_total", "vista_resultado")
        }),
    )

    @admin.display(description="Curricular")
    def col_curricular(self, obj):
        return f"{obj.puntaje_evaluacion_curricular()} / 40"

    @admin.display(description="Capacidad Docente")
    def col_capacidad_docente(self, obj):
        return f"{obj.puntaje_capacidad_docente()} / 35"

    @admin.display(description="Entrevista")
    def col_entrevista(self, obj):
        return f"{obj.puntaje_entrevista_personal()} / 25"

    @admin.display(description="Puntaje Total")
    def col_puntaje_total(self, obj):
        return f"{obj.puntaje_total()} / 100"

    @admin.display(description="Resultado")
    def col_resultado(self, obj):
        color = "#1c5c33" if obj.resultado().startswith("GANADOR") else "#a83232"
        return format_html('<strong style="color:{}">{}</strong>', color, obj.resultado())

    @admin.display(description="Puntaje bloque 1 (Grados y títulos)")
    def vista_puntaje_grados_titulos(self, obj):
        return obj.puntaje_grados_titulos()

    @admin.display(description="Puntaje bloque 2 (Capacitaciones)")
    def vista_puntaje_capacitaciones(self, obj):
        return obj.puntaje_capacitaciones()

    @admin.display(description="Puntaje bloque 3 (Eventos e investigación)")
    def vista_puntaje_eventos_investigacion(self, obj):
        return obj.puntaje_eventos_investigacion()

    @admin.display(description="Puntaje bloque 4 (Otros programas)")
    def vista_puntaje_otros_programas(self, obj):
        return obj.puntaje_otros_programas()

    @admin.display(description="Puntaje bloque 5 (Experiencia docente)")
    def vista_puntaje_experiencia_docente(self, obj):
        return obj.puntaje_experiencia_docente()

    @admin.display(description="Puntaje bloque 6 (Experiencia profesional)")
    def vista_puntaje_experiencia_profesional(self, obj):
        return obj.puntaje_experiencia_profesional()

    @admin.display(description="TOTAL Evaluación Curricular (máx. 40, mínimo 20)")
    def vista_puntaje_evaluacion_curricular(self, obj):
        return format_html("<strong>{} / 40</strong>", obj.puntaje_evaluacion_curricular())

    @admin.display(description="Formato imprimible")
    def vista_imprimir_ficha(self, obj):
        if not obj.pk:
            return "Guarda el postulante primero."
        url = reverse("procesodocente:imprimir_ficha_curricular", args=[obj.pk])
        return format_html(
            '<a class="button" href="{}" target="_blank" style="background:#16543f;color:#fff;'
            'padding:.4rem .8rem;border-radius:.3rem;text-decoration:none;display:inline-block">'
            '🖨️ Imprimir ficha de evaluación curricular</a>',
            url,
        )

    @admin.display(description="TOTAL Capacidad Docente (máx. 35, mínimo 30)")
    def vista_puntaje_capacidad_docente(self, obj):
        return format_html("<strong>{} / 35</strong>", obj.puntaje_capacidad_docente())

    @admin.display(description="TOTAL Entrevista Personal (máx. 25, mínimo 10)")
    def vista_puntaje_entrevista_personal(self, obj):
        return format_html("<strong>{} / 25</strong>", obj.puntaje_entrevista_personal())

    @admin.display(description="PUNTAJE TOTAL (máx. 100, mínimo 60)")
    def vista_puntaje_total(self, obj):
        return format_html("<strong style='font-size:1.2em'>{} / 100</strong>", obj.puntaje_total())

    @admin.display(description="Resultado")
    def vista_resultado(self, obj):
        color = "#1c5c33" if obj.resultado().startswith("GANADOR") else "#a83232"
        return format_html('<strong style="font-size:1.2em; color:{}">{}</strong>', color, obj.resultado())

    @admin.action(description="Vincular/crear Docente (solo postulantes GANADORES; por DNI, nunca por nombre parecido)")
    def vincular_o_crear_docente_action(self, request, queryset):
        creados = actualizados = fallidos = 0
        for postulante in queryset:
            try:
                _, creado = postulante.vincular_o_crear_docente()
                if creado:
                    creados += 1
                else:
                    actualizados += 1
            except ValueError as exc:
                fallidos += 1
                self.message_user(
                    request, f"{postulante.nombre_completo}: {exc}", level="warning"
                )
        self.message_user(
            request,
            f"Docentes creados: {creados}. Docentes actualizados: {actualizados}. "
            f"Sin procesar (no es ganador o faltó DNI): {fallidos}.",
        )
