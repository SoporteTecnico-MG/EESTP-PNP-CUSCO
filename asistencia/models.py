from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator


class Especialidad(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Especialidad"
        verbose_name_plural = "Especialidades"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Docente(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"

    dni = models.CharField(
        max_length=8,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Opcional al crear el docente; se puede regularizar después. "
        "No es necesario para que el control de asistencia funcione (eso usa el ID Biometrico).",
    )
    apellidos_nombres = models.CharField(max_length=200)
    grado = models.CharField(max_length=100, blank=True)
    celular = models.CharField(max_length=20, blank=True)
    id_biometrico = models.CharField(
        max_length=24,
        unique=True,
        help_text="ID de usuario tal como quedó registrado en el iClock880. "
        "Se recomienda que sea igual al DNI; si el equipo no lo permite, "
        "se usa un código propio y este campo mapea a ese docente.",
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)
    fecha_ingreso = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Docente"
        verbose_name_plural = "Docentes"
        ordering = ["apellidos_nombres"]

    def __str__(self):
        return f"{self.apellidos_nombres} ({self.dni or 'sin DNI, ID ' + self.id_biometrico})"


class Promocion(models.Model):
    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "Activa"
        CULMINADA = "CULMINADA", "Culminada"

    nombre = models.CharField(max_length=100, unique=True, help_text='Ej. "JUSTICIEROS 2025-I"')
    anio_ingreso = models.PositiveIntegerField()
    fecha_inicio_formacion = models.DateField()
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVA)

    class Meta:
        verbose_name = "Promoción"
        verbose_name_plural = "Promociones"
        ordering = ["-anio_ingreso", "nombre"]

    def __str__(self):
        return self.nombre


class Aula(models.Model):
    promocion = models.ForeignKey(Promocion, on_delete=models.CASCADE, related_name="aulas")
    numero = models.PositiveSmallIntegerField(help_text="1 a 14")
    especialidad = models.ForeignKey(
        Especialidad,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Se asigna a partir del III período académico.",
    )

    class Meta:
        verbose_name = "Aula"
        verbose_name_plural = "Aulas"
        ordering = ["promocion__nombre", "numero"]
        unique_together = ("promocion", "numero")

    def __str__(self):
        return f"{self.promocion.nombre} · {self.codigo}"

    @property
    def codigo(self):
        """Ej. Aula 1 -> 'A_1', Aula 2 -> 'B_2', Aula 3 -> 'C_3'..."""
        if 1 <= self.numero <= 26:
            letra = chr(64 + self.numero)
        else:
            letra = str(self.numero)
        return f"{letra}_{self.numero}"


class PeriodoAcademico(models.Model):
    class Estado(models.TextChoices):
        PLANIFICADO = "PLANIFICADO", "Planificado"
        EN_CURSO = "EN_CURSO", "En curso"
        CERRADO = "CERRADO", "Cerrado"

    promocion = models.ForeignKey(Promocion, on_delete=models.CASCADE, related_name="periodos")
    numero_periodo = models.PositiveSmallIntegerField(help_text="1 a 6")
    nombre = models.CharField(max_length=100, blank=True, help_text='Ej. "III Periodo"')
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.PLANIFICADO)
    usa_sabado = models.BooleanField(
        default=True,
        help_text="Si este período dicta clases los sábados. Al desactivarlo, el "
        "sábado deja de aparecer en el horario y no se puede programar cursos ese día.",
    )

    class Meta:
        verbose_name = "Período Académico"
        verbose_name_plural = "Períodos Académicos"
        ordering = ["promocion", "numero_periodo"]
        unique_together = ("promocion", "numero_periodo")

    def __str__(self):
        return f"{self.promocion.nombre} - {self.nombre or f'Periodo {self.numero_periodo}'}"

    def clean(self):
        if self.fecha_inicio and self.fecha_fin and self.fecha_inicio >= self.fecha_fin:
            raise ValidationError("La fecha de inicio debe ser anterior a la fecha de fin.")


class Curso(models.Model):
    nombre = models.CharField(max_length=150)
    especialidad = models.ForeignKey(
        Especialidad,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Vacío si el curso es común a todas las especialidades.",
    )

    class Meta:
        verbose_name = "Curso"
        verbose_name_plural = "Cursos"
        ordering = ["nombre"]
    def __str__(self):
        if self.especialidad_id:
            return f"{self.nombre} ({self.especialidad.nombre})"
        return self.nombre


class OfertaCurso(models.Model):
    periodo_academico = models.ForeignKey(
        PeriodoAcademico, on_delete=models.CASCADE, related_name="ofertas_curso"
    )
    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name="ofertas")

    class Meta:
        verbose_name = "Oferta de Curso"
        verbose_name_plural = "Ofertas de Curso"
        ordering = [
            "periodo_academico__promocion__nombre",
            "periodo_academico__numero_periodo",
            "curso__nombre",
        ]
        unique_together = ("periodo_academico", "curso")

    def __str__(self):
        return f"{self.periodo_academico} · {self.curso.nombre}"

    def horas_pedagogicas(self):
        """Horas de clase reales (sin contar recesos) sumando todos sus bloques.
        El horario es el mismo para todas las aulas/secciones que dicten este curso."""
        total = 0
        for b in self.bloques.all():
            total += HoraPedagogica.objects.filter(
                tipo="CLASE",
                numero_bloque__gte=b.hora_pedagogica_inicio.numero_bloque,
                numero_bloque__lte=b.hora_pedagogica_fin.numero_bloque,
            ).count()
        return total


class HoraPedagogica(models.Model):
    class Tipo(models.TextChoices):
        CLASE = "CLASE", "Clase"
        RECESO = "RECESO", "Receso"
        ALMUERZO = "ALMUERZO", "Almuerzo"

    numero_bloque = models.PositiveSmallIntegerField(unique=True)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.CLASE)

    class Meta:
        verbose_name = "Hora Pedagógica"
        verbose_name_plural = "Grilla de Horas Pedagógicas"
        ordering = ["numero_bloque"]

    def __str__(self):
        return f"HP{self.numero_bloque} ({self.hora_inicio.strftime('%H:%M')}-{self.hora_fin.strftime('%H:%M')})"


class Asignacion(models.Model):
    aula = models.ForeignKey(Aula, on_delete=models.CASCADE, related_name="asignaciones")
    oferta_curso = models.ForeignKey(
        OfertaCurso, on_delete=models.CASCADE, related_name="asignaciones"
    )
    docente = models.ForeignKey(Docente, on_delete=models.PROTECT, related_name="asignaciones")

    @property
    def horas_pedagogicas_totales(self):
        """El horario (y sus horas) es del curso, no de la asignación: es el mismo
        para todas las aulas que lo dicten en el período. Se calcula, no se guarda."""
        return self.oferta_curso.horas_pedagogicas()

    class Meta:
        verbose_name = "Asignación"
        verbose_name_plural = "Asignaciones"
        ordering = ["aula", "oferta_curso"]
        unique_together = ("aula", "oferta_curso")

    def __str__(self):
        return f"{self.docente} — {self.oferta_curso.curso.nombre} — {self.aula}"


class BloqueHorario(models.Model):
    class Dia(models.IntegerChoices):
        LUNES = 1, "Lunes"
        MARTES = 2, "Martes"
        MIERCOLES = 3, "Miércoles"
        JUEVES = 4, "Jueves"
        VIERNES = 5, "Viernes"
        SABADO = 6, "Sábado"
        DOMINGO = 7, "Domingo"

    oferta_curso = models.ForeignKey(OfertaCurso, on_delete=models.CASCADE, related_name="bloques")
    dia_semana = models.PositiveSmallIntegerField(choices=Dia.choices)
    hora_pedagogica_inicio = models.ForeignKey(
        HoraPedagogica, on_delete=models.PROTECT, related_name="bloques_inicio"
    )
    hora_pedagogica_fin = models.ForeignKey(
        HoraPedagogica, on_delete=models.PROTECT, related_name="bloques_fin"
    )

    class Meta:
        verbose_name = "Bloque de Horario"
        verbose_name_plural = "Bloques de Horario"
        ordering = ["dia_semana", "hora_pedagogica_inicio"]

    def __str__(self):
        return (
            f"{self.get_dia_semana_display()} "
            f"{self.hora_pedagogica_inicio.hora_inicio.strftime('%H:%M')}-"
            f"{self.hora_pedagogica_fin.hora_fin.strftime('%H:%M')} — {self.oferta_curso}"
        )


class MarcacionBiometrica(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada"
        SALIDA = "SALIDA", "Salida"
        DESCONOCIDO = "DESCONOCIDO", "Desconocido"

    id_biometrico = models.CharField(max_length=24, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    tipo = models.CharField(max_length=15, choices=Tipo.choices, default=Tipo.DESCONOCIDO)
    origen_dispositivo = models.CharField(max_length=50, default="iClock880")
    importado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Marcación Biométrica"
        verbose_name_plural = "Marcaciones Biométricas"
        ordering = ["-timestamp"]
        unique_together = ("id_biometrico", "timestamp", "origen_dispositivo")

    def __str__(self):
        return f"{self.id_biometrico} — {self.timestamp}"


class AsistenciaResuelta(models.Model):
    class Estado(models.TextChoices):
        PUNTUAL = "PUNTUAL", "Puntual"
        TARDANZA = "TARDANZA", "Tardanza"
        FALTA = "FALTA", "Falta"
        SOLO_ENTRADA = "SOLO_ENTRADA", "Solo marcó entrada"
        SOLO_SALIDA = "SOLO_SALIDA", "Solo marcó salida"
        NO_PROGRAMADO = "NO_PROGRAMADO", "No programado"
        AMBIGUO = "AMBIGUO", "Ambiguo (revisar)"
        RECUPERACION = "RECUPERACION", "Recuperación nocturna"

    docente = models.ForeignKey(Docente, on_delete=models.PROTECT, related_name="asistencias")
    asignacion = models.ForeignKey(
        Asignacion, on_delete=models.PROTECT, related_name="asistencias", null=True, blank=True
    )
    fecha = models.DateField(db_index=True)
    marcacion_entrada = models.ForeignKey(
        MarcacionBiometrica,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asistencias_como_entrada",
    )
    marcacion_salida = models.ForeignKey(
        MarcacionBiometrica,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asistencias_como_salida",
    )
    estado = models.CharField(max_length=15, choices=Estado.choices)
    minutos_tardanza = models.PositiveIntegerField(default=0)
    horas_efectivas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    horas_pedagogicas_descontadas = models.PositiveSmallIntegerField(
        default=0,
        help_text="Horas pedagógicas (45 min c/u) que ya habían transcurrido por "
        "completo al momento de marcar entrada, cuando la tardanza es de 15 minutos "
        "o más. Se descuentan automáticamente, sin revisión manual.",
    )
    salida_anticipada = models.BooleanField(
        default=False,
        help_text="El docente marcó salida antes de la hora programada de fin. "
        "No se descuenta solo — queda para que jefatura decida.",
    )
    requiere_revision = models.BooleanField(default=False)
    corregido_manualmente = models.BooleanField(
        default=False,
        help_text="Jefatura ajustó el estado a mano desde el reporte. Mientras esté "
        "activo, cerrar_dia ya no recalcula este registro automáticamente (así una "
        "resincronización o un cierre tardío no borra la corrección).",
    )

    class Meta:
        verbose_name = "Asistencia Resuelta"
        verbose_name_plural = "Asistencias Resueltas"
        ordering = ["-fecha", "docente"]
        unique_together = ("docente", "asignacion", "fecha")

    def __str__(self):
        return f"{self.docente} — {self.fecha} — {self.get_estado_display()}"


class Feriado(models.Model):
    """Días en los que no hay obligación de marcar: feriados nacionales o
    suspensión de labores por disposición superior. El motor de resolución
    (cerrar_dia) no genera Falta ni ningún estado para estas fechas."""

    class Tipo(models.TextChoices):
        FERIADO_NACIONAL = "FERIADO_NACIONAL", "Feriado nacional"
        SUSPENSION_SUPERIOR = "SUSPENSION_SUPERIOR", "Suspensión por disposición superior"

    fecha = models.DateField(unique=True)
    descripcion = models.CharField(max_length=200)
    tipo = models.CharField(max_length=25, choices=Tipo.choices, default=Tipo.FERIADO_NACIONAL)

    class Meta:
        verbose_name = "Feriado / Suspensión"
        verbose_name_plural = "Feriados y Suspensiones"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.fecha} — {self.descripcion}"


class RegistroActividad(models.Model):
    """Bitácora de acciones sensibles hechas por usuarios del sistema
    (login/logout, correcciones de asistencia, sincronizaciones manuales,
    cambios de horario). Solo visible para el administrador general
    (superusuario) desde el admin."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="actividades"
    )
    fecha_hora = models.DateTimeField(auto_now_add=True, db_index=True)
    accion = models.CharField(max_length=100)
    detalle = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Registro de Actividad"
        verbose_name_plural = "Registro de Actividad"
        ordering = ["-fecha_hora"]

    def __str__(self):
        return f"{self.usuario} — {self.accion} — {self.fecha_hora:%d/%m/%Y %H:%M}"


def registrar_actividad(request, accion, detalle=""):
    """Guarda una fila en la bitácora. `request` puede ser None (ej. señales
    de login donde a veces no hay request explícito en el handler)."""
    usuario = getattr(request, "user", None)
    if usuario is not None and not usuario.is_authenticated:
        usuario = None
    RegistroActividad.objects.create(usuario=usuario, accion=accion, detalle=detalle)


class Postulante(models.Model):
    """Calificación de postulantes a la docencia — Manual del Personal Docente
    de la ENFPP PNP (RD N°022-2022-ENFPP-PNP), Cap. III-B y Anexos 10 a 13.

    Puntaje Total = Evaluación Curricular + Capacidad Docente + Entrevista
    Personal. Las tres etapas son eliminatorias, con puntaje mínimo propio
    cada una (ver Anexo 10, cuadro de puntajes mínimos/máximos)."""

    class TablaCurricular(models.TextChoices):
        ANEXO_10 = "ANEXO_10", "Anexo 10 — Concurso público general (civiles / EO-ESCFOCON-ESCPOGRA)"
        ANEXO_13 = "ANEXO_13", "Anexo 13 — Ingreso de Suboficiales como docente (EESTP)"

    class Procedencia(models.TextChoices):
        PNP = "PNP", "PNP"
        FFAA = "FFAA", "Fuerzas Armadas"
        CIVIL = "CIVIL", "Civil"
        EXTRANJERO = "EXTRANJERO", "Extranjero"

    class Escuela(models.TextChoices):
        EESTP = "EESTP", "EESTP PNP"
        EO = "EO", "Escuela de Oficiales PNP"
        ESCFOCON = "ESCFOCON", "ESCFOCON PNP"
        ESCPOGRA = "ESCPOGRA", "ESCPOGRA PNP"

    # --- Datos generales (Anexo 06) ---
    apellidos_nombres = models.CharField(max_length=200)
    dni_cip = models.CharField("DNI / CIP", max_length=20, blank=True)
    grado = models.CharField(max_length=100, blank=True, help_text="Grado policial o 'Civil'")
    procedencia = models.CharField(max_length=12, choices=Procedencia.choices, default=Procedencia.CIVIL)
    escuela = models.CharField(max_length=10, choices=Escuela.choices, default=Escuela.EESTP)
    unidad_didactica = models.CharField("Unidad didáctica / curso al que postula", max_length=200)
    convocatoria = models.CharField(max_length=100, help_text="Ej. 2026-II, Semestre I 2026, etc.")
    fecha_evaluacion = models.DateField(null=True, blank=True)
    tabla_curricular = models.CharField(
        max_length=10, choices=TablaCurricular.choices, default=TablaCurricular.ANEXO_10,
        help_text="Según el origen del postulante, define cómo se puntúan grados y títulos (Anexo 10 vs Anexo 13).",
    )

    # --- Evaluación Curricular — bloque 1: Grados y Títulos (máx. 20) ---
    tiene_titulo_profesional = models.BooleanField(
        "Título Profesional Universitario / en Adm. y CC. Policiales", default=False
    )
    tiene_titulo_profesional_tecnico = models.BooleanField(
        "Título Profesional Técnico en ciencias policiales (solo Anexo 13)", default=False
    )
    tiene_maestria = models.BooleanField("Grado académico de Maestro", default=False)
    tiene_doctorado = models.BooleanField("Grado académico de Doctor", default=False)
    tiene_segunda_especialidad = models.BooleanField("Segunda especialidad o título de especialista", default=False)

    # --- bloque 2: Actualizaciones y capacitaciones afines (máx. 3) ---
    diplomados_120h = models.PositiveSmallIntegerField(
        "Diplomados afines ≥120h (1.0 c/u, tope 2)", default=0
    )
    programas_16_96h_afines = models.PositiveSmallIntegerField(
        "Programas afines 16-96h (0.5 c/u, tope 2)", default=0
    )

    # --- bloque 3: Participación en eventos científicos e investigación (máx. 3) ---
    ponente_eventos = models.PositiveSmallIntegerField("Ponente en eventos académicos (0.5 c/u, tope 1)", default=0)
    asistente_eventos = models.PositiveSmallIntegerField("Asistente a eventos académicos (0.5 c/u, tope 1)", default=0)
    investigaciones = models.PositiveSmallIntegerField("Investigaciones en la especialidad (1.0 c/u, tope 1)", default=0)
    publicaciones = models.PositiveSmallIntegerField("Textos y/o libros publicados (1.0 c/u, tope 1)", default=0)

    # --- bloque 4: Otros programas de formación continua (máx. 4) ---
    programas_96h_otros = models.PositiveSmallIntegerField("Programas ≥96h (1.0 c/u, tope 2)", default=0)
    programas_16_96h_otros = models.PositiveSmallIntegerField("Programas 16-96h (0.5 c/u, tope 2)", default=0)
    cursos_ofimatica_24h = models.PositiveSmallIntegerField("Cursos de ofimática ≥24h (0.5 c/u, tope 2)", default=0)

    # --- bloque 5: Experiencia docente universitaria (máx. 4) ---
    pregrado_ciclos = models.PositiveSmallIntegerField(
        "Docencia nivel pregrado, en ciclos (0.5 c/ciclo)", default=0
    )
    maestria_cursos = models.PositiveSmallIntegerField(
        "Docencia posgrado Maestría, en cursos (0.5 c/curso, tope 1)", default=0
    )
    doctorado_cursos = models.PositiveSmallIntegerField(
        "Docencia posgrado Doctorado, en cursos (0.5 c/curso, tope 1; solo Anexo 10)", default=0
    )

    # --- bloque 6: Experiencia profesional (máx. 6) ---
    experiencia_profesional_anios = models.PositiveSmallIntegerField(
        "Ejercicio profesional no docente, en años (1.0 c/año, tope 6)", default=0
    )

    # --- Capacidad Docente (Anexo 11, máx. 35: 5 bloques de 0 a 7) ---
    cd_planificacion = models.PositiveSmallIntegerField(
        "Planificación y evaluación de sesiones", default=0, validators=[MaxValueValidator(7)]
    )
    cd_dominio_pedagogico = models.PositiveSmallIntegerField(
        "Dominio pedagógico", default=0, validators=[MaxValueValidator(7)]
    )
    cd_dominio_tecnico = models.PositiveSmallIntegerField(
        "Dominio técnico", default=0, validators=[MaxValueValidator(7)]
    )
    cd_comunicacion = models.PositiveSmallIntegerField(
        "Comunicación efectiva", default=0, validators=[MaxValueValidator(7)]
    )
    cd_recursos_tecnologicos = models.PositiveSmallIntegerField(
        "Uso de recursos tecnológicos", default=0, validators=[MaxValueValidator(7)]
    )

    # --- Entrevista Personal (Anexo 12, máx. 25: 5 bloques de 0 a 5) ---
    ep_proceso_ensenanza = models.PositiveSmallIntegerField(
        "Proceso de enseñanza-aprendizaje", default=0, validators=[MaxValueValidator(5)]
    )
    ep_desarrollo_institucional = models.PositiveSmallIntegerField(
        "Desarrollo institucional", default=0, validators=[MaxValueValidator(5)]
    )
    ep_especialidad_experiencia = models.PositiveSmallIntegerField(
        "Especialidad y experiencia", default=0, validators=[MaxValueValidator(5)]
    )
    ep_investigacion_innovacion = models.PositiveSmallIntegerField(
        "Investigación e innovación", default=0, validators=[MaxValueValidator(5)]
    )
    ep_personalidad = models.PositiveSmallIntegerField(
        "Personalidad", default=0, validators=[MaxValueValidator(5)]
    )

    class Meta:
        verbose_name = "Postulante (calificación docente)"
        verbose_name_plural = "Postulantes (calificación docente)"
        ordering = ["convocatoria", "unidad_didactica", "apellidos_nombres"]

    def __str__(self):
        return f"{self.apellidos_nombres} — {self.unidad_didactica} ({self.convocatoria})"

    # --- Puntajes calculados ---

    def puntaje_grados_titulos(self):
        """Bloque 1 — depende de la tabla curricular (Anexo 10 vs Anexo 13)."""
        if self.tabla_curricular == self.TablaCurricular.ANEXO_13:
            total = 0
            if self.tiene_titulo_profesional:
                total += 5.0
            if self.tiene_titulo_profesional_tecnico:
                total += 4.0
            if self.tiene_maestria or self.tiene_doctorado:
                total += 6.0
            if self.tiene_segunda_especialidad:
                total += 5.0
            return total
        total = 0
        if self.tiene_titulo_profesional:
            total += 4.0
        if self.tiene_doctorado:
            total += 7.0
        if self.tiene_maestria:
            total += 5.0
        if self.tiene_segunda_especialidad:
            total += 4.0
        return total

    def puntaje_capacitaciones(self):
        return min(self.diplomados_120h * 1.0, 2.0) + min(self.programas_16_96h_afines * 0.5, 1.0)

    def puntaje_eventos_investigacion(self):
        return (
            min(self.ponente_eventos * 0.5, 0.5)
            + min(self.asistente_eventos * 0.5, 0.5)
            + min(self.investigaciones * 1.0, 1.0)
            + min(self.publicaciones * 1.0, 1.0)
        )

    def puntaje_otros_programas(self):
        return (
            min(self.programas_96h_otros * 1.0, 2.0)
            + min(self.programas_16_96h_otros * 0.5, 1.0)
            + min(self.cursos_ofimatica_24h * 0.5, 1.0)
        )

    def puntaje_experiencia_docente(self):
        if self.tabla_curricular == self.TablaCurricular.ANEXO_13:
            return min(self.pregrado_ciclos * 0.5, 3.0) + min(self.maestria_cursos * 0.5, 1.0)
        return (
            min(self.pregrado_ciclos * 0.5, 2.0)
            + min(self.maestria_cursos * 0.5, 1.0)
            + min(self.doctorado_cursos * 0.5, 1.0)
        )

    def puntaje_experiencia_profesional(self):
        return min(self.experiencia_profesional_anios * 1.0, 6.0)

    def puntaje_evaluacion_curricular(self):
        return round(
            self.puntaje_grados_titulos()
            + self.puntaje_capacitaciones()
            + self.puntaje_eventos_investigacion()
            + self.puntaje_otros_programas()
            + self.puntaje_experiencia_docente()
            + self.puntaje_experiencia_profesional(),
            2,
        )

    def puntaje_capacidad_docente(self):
        return (
            self.cd_planificacion
            + self.cd_dominio_pedagogico
            + self.cd_dominio_tecnico
            + self.cd_comunicacion
            + self.cd_recursos_tecnologicos
        )

    def puntaje_entrevista_personal(self):
        return (
            self.ep_proceso_ensenanza
            + self.ep_desarrollo_institucional
            + self.ep_especialidad_experiencia
            + self.ep_investigacion_innovacion
            + self.ep_personalidad
        )

    def puntaje_total(self):
        return round(
            self.puntaje_evaluacion_curricular()
            + self.puntaje_capacidad_docente()
            + self.puntaje_entrevista_personal(),
            2,
        )

    # --- Aptitud por etapa (eliminatorias, Anexo 10) ---
    def apto_curricular(self):
        return self.puntaje_evaluacion_curricular() >= 20

    def apto_capacidad_docente(self):
        return self.puntaje_capacidad_docente() >= 30

    def apto_entrevista(self):
        return self.puntaje_entrevista_personal() >= 10

    def resultado(self):
        if not (self.apto_curricular() and self.apto_capacidad_docente() and self.apto_entrevista()):
            return "NO APTO"
        return "GANADOR (potencial)" if self.puntaje_total() >= 60 else "NO APTO"

    def grado_academico_nivel(self):
        """Para el criterio de desempate 'mayor grado académico'."""
        if self.tiene_doctorado:
            return 3
        if self.tiene_maestria:
            return 2
        if self.tiene_titulo_profesional or self.tiene_titulo_profesional_tecnico:
            return 1
        return 0
