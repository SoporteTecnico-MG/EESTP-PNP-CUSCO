from urllib.parse import urlencode

from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html
from . import models
from . import views as asistencia_views

admin.site.site_header = "EESTP PNP CUSCO — Sistema Institucional"
admin.site.site_title = "Sistema Institucional"
admin.site.index_title = "Panel de administración"


def _login_unificado(request, extra_context=None):
    """El admin de Django trae su propia pantalla de login (/admin/login/),
    aparte de la pública que ya diseñamos (/login/) — esto la reemplaza para
    que todo el sistema use una sola pantalla de inicio de sesión."""
    next_url = request.GET.get("next") or reverse("admin:index")
    return redirect(f"{reverse('asistencia:login')}?{urlencode({'next': next_url})}")


admin.site.login = _login_unificado

_admin_index = admin.site.index


def _index_con_estadisticas(request, extra_context=None):
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
    return _admin_index(request, extra_context)


admin.site.index = _index_con_estadisticas

_admin_get_urls = admin.site.get_urls


def _get_urls():
    custom = [
        path(
            "armar-horario/",
            admin.site.admin_view(asistencia_views.asignar_horario),
            name="armar_horario",
        ),
        path(
            "ver-horario/",
            admin.site.admin_view(asistencia_views.ver_horario),
            name="ver_horario",
        ),
        path(
            "reporte-asistencia/",
            admin.site.admin_view(asistencia_views.reporte_asistencia),
            name="reporte_asistencia",
        ),
        path(
            "corregir-asistencia/<int:pk>/",
            admin.site.admin_view(asistencia_views.corregir_asistencia),
            name="corregir_asistencia",
        ),
        path(
            "corregir-asistencia-lote/",
            admin.site.admin_view(asistencia_views.corregir_asistencia_lote),
            name="corregir_asistencia_lote",
        ),
        path(
            "calendario-asistencia/",
            admin.site.admin_view(asistencia_views.calendario_asistencia),
            name="calendario_asistencia",
        ),
        path(
            "cuadro-inasistencia/",
            admin.site.admin_view(asistencia_views.cuadro_inasistencia),
            name="cuadro_inasistencia",
        ),
        path(
            "sincronizar-biometrico/",
            admin.site.admin_view(asistencia_views.sincronizar_biometrico_vista),
            name="sincronizar_biometrico",
        ),
    ]
    return custom + _admin_get_urls()


admin.site.get_urls = _get_urls


@admin.register(models.Especialidad)
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


@admin.register(models.Docente)
class DocenteAdmin(admin.ModelAdmin):
    list_display = ("dni", "apellidos_nombres", "grado", "celular", "id_biometrico", "estado")
    list_filter = ("estado", "grado")
    search_fields = ("dni", "apellidos_nombres", "id_biometrico")
    ordering = ("apellidos_nombres",)
    inlines = [AsignacionInline]


@admin.register(models.Promocion)
class PromocionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "anio_ingreso", "fecha_inicio_formacion", "estado")
    list_filter = ("estado", "anio_ingreso")
    search_fields = ("nombre",)
    ordering = ("-anio_ingreso", "nombre")


@admin.register(models.Aula)
class AulaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "promocion", "especialidad")
    list_filter = ("promocion", "especialidad")
    search_fields = ("numero", "promocion__nombre")
    ordering = ("promocion", "numero")


@admin.register(models.PeriodoAcademico)
class PeriodoAcademicoAdmin(admin.ModelAdmin):
    list_display = ("promocion", "numero_periodo", "nombre", "fecha_inicio", "fecha_fin", "estado", "usa_sabado")
    list_editable = ("usa_sabado",)
    list_filter = ("promocion", "estado")
    ordering = ("promocion", "numero_periodo")


@admin.register(models.Curso)
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


@admin.register(models.OfertaCurso)
class OfertaCursoAdmin(admin.ModelAdmin):
    list_display = ("periodo_academico", "curso", "horas_pedagogicas")
    list_filter = ("periodo_academico",)
    search_fields = ("curso__nombre", "periodo_academico__promocion__nombre")
    ordering = ("periodo_academico", "curso")
    inlines = [BloqueHorarioInline]


@admin.register(models.HoraPedagogica)
class HoraPedagogicaAdmin(admin.ModelAdmin):
    list_display = ("numero_bloque", "hora_inicio", "hora_fin", "tipo")
    ordering = ("numero_bloque",)


@admin.register(models.Asignacion)
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
        url = f"{reverse('admin:ver_horario')}?promocion={obj.aula.promocion_id}&aula={obj.aula_id}"
        return format_html(
            '<a class="button" href="{}" style="background:#1d5a43;color:#fff;padding:.4rem .8rem;'
            'border-radius:.3rem;text-decoration:none;display:inline-block">'
            'Ver horario visual de esta aula</a>',
            url,
        )

    enlace_ver_horario.short_description = "Horario visual"


@admin.register(models.BloqueHorario)
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

        return redirect(reverse("admin:armar_horario"))

    def asignado_a(self, obj):
        return _asignaciones_texto(obj.oferta_curso)

    asignado_a.short_description = "Aula: Docente"


@admin.register(models.MarcacionBiometrica)
class MarcacionBiometricaAdmin(admin.ModelAdmin):
    list_display = ("id_biometrico", "timestamp", "tipo", "origen_dispositivo", "importado_en")
    list_filter = ("tipo", "origen_dispositivo")
    search_fields = ("id_biometrico",)
    ordering = ("-timestamp",)
    date_hierarchy = "timestamp"


@admin.register(models.AsistenciaResuelta)
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


@admin.register(models.Feriado)
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
