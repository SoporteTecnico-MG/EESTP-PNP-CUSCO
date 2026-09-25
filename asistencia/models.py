from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator


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
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="docente",
        help_text="Cuenta para entrar al Aula Virtual — se crea con la acción "
        '"Crear acceso al Aula Virtual" del listado de Docentes.',
    )
    password_temporal = models.BooleanField(
        default=False,
        help_text="Su contraseña sigue siendo la que se le puso por defecto (su DNI) — "
        "el sistema lo obliga a cambiarla antes de dejarlo ver el Aula Virtual.",
    )

    class Meta:
        verbose_name = "Docente"
        verbose_name_plural = "Docentes"
        ordering = ["apellidos_nombres"]

    def __str__(self):
        return f"{self.apellidos_nombres} ({self.dni or 'sin DNI, ID ' + self.id_biometrico})"

    def crear_acceso_aula_virtual(self):
        """Crea (si no existe ya) el usuario para entrar al Aula Virtual:
        usuario "<DNI>@pnp.edu", contraseña por defecto el propio DNI (el
        docente la cambia desde "Mi cuenta" en su primer ingreso). Requiere
        que el Docente tenga DNI. Devuelve (user, creado: bool)."""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        if self.usuario_id:
            return self.usuario, False
        if not self.dni:
            raise ValueError(f"{self.apellidos_nombres} no tiene DNI registrado — no se puede crear su acceso.")

        User = get_user_model()
        username = f"{self.dni}@pnp.edu"
        usuario = User.objects.filter(username=username).first()
        creado = False
        if usuario is None:
            nombres = self.apellidos_nombres.split()
            usuario = User.objects.create_user(
                username=username,
                password=self.dni,
                first_name=nombres[-1] if nombres else "",
                last_name=" ".join(nombres[:-1]) if len(nombres) > 1 else "",
            )
            creado = True
        grupo_docentes, _ = Group.objects.get_or_create(name="Docentes")
        usuario.groups.add(grupo_docentes)
        self.usuario = usuario
        self.password_temporal = True
        self.save(update_fields=["usuario", "password_temporal"])
        return usuario, creado


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


class Estudiante(models.Model):
    """Cadete/Alumno del Aula Virtual. No hace falta un modelo aparte de
    "Matrícula": el Aula ya es la sección/cohorte del estudiante, y los
    cursos que le corresponden salen solos de las Asignaciones hechas a
    esa misma Aula (docente + curso + aula) — no hay que inscribirlo curso
    por curso."""

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        RETIRADO = "RETIRADO", "Retirado"

    dni = models.CharField(max_length=8, unique=True, null=True, blank=True, db_index=True)
    apellidos_nombres = models.CharField(max_length=200)
    celular = models.CharField(max_length=20, blank=True)
    aula = models.ForeignKey(Aula, on_delete=models.PROTECT, related_name="estudiantes")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)
    fecha_ingreso = models.DateField(null=True, blank=True)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="estudiante",
        help_text="Cuenta para entrar al Aula Virtual — se crea con la acción "
        '"Crear acceso al Aula Virtual" del listado de Estudiantes.',
    )
    password_temporal = models.BooleanField(
        default=False,
        help_text="Su contraseña sigue siendo la que se le puso por defecto (su DNI) — "
        "el sistema lo obliga a cambiarla antes de dejarlo ver el Aula Virtual.",
    )

    class Meta:
        verbose_name = "Estudiante"
        verbose_name_plural = "Estudiantes"
        ordering = ["apellidos_nombres"]

    def __str__(self):
        return f"{self.apellidos_nombres} ({self.aula})"

    def crear_acceso_aula_virtual(self):
        """Crea (si no existe ya) el usuario para entrar al Aula Virtual:
        usuario "<DNI>@cadete.pnp.edu", contraseña por defecto el propio
        DNI. Requiere que el Estudiante tenga DNI. Devuelve (user, creado: bool)."""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        if self.usuario_id:
            return self.usuario, False
        if not self.dni:
            raise ValueError(f"{self.apellidos_nombres} no tiene DNI registrado — no se puede crear su acceso.")

        User = get_user_model()
        username = f"{self.dni}@cadete.pnp.edu"
        usuario = User.objects.filter(username=username).first()
        creado = False
        if usuario is None:
            nombres = self.apellidos_nombres.split()
            usuario = User.objects.create_user(
                username=username,
                password=self.dni,
                first_name=nombres[-1] if nombres else "",
                last_name=" ".join(nombres[:-1]) if len(nombres) > 1 else "",
            )
            creado = True
        grupo_estudiantes, _ = Group.objects.get_or_create(name="Estudiantes")
        usuario.groups.add(grupo_estudiantes)
        self.usuario = usuario
        self.password_temporal = True
        self.save(update_fields=["usuario", "password_temporal"])
        return usuario, creado


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


class MaterialClase(models.Model):
    """Aula Virtual — material que el Docente publica para el Aula (sección)
    a la que dicta, según su Asignación. Se guarda como enlace externo
    (Drive, YouTube, etc.), no como archivo subido: el servidor de
    despliegue no garantiza guardar archivos entre reinicios, y un enlace
    no tiene ese riesgo. Todavía no hay Cadetes/Estudiantes con cuenta en
    el sistema, así que por ahora solo lo ve el propio Docente y el staff;
    en cuanto exista esa cuenta, se le muestra lo mismo sin cambiar el
    modelo."""

    class Tipo(models.TextChoices):
        ENLACE = "ENLACE", "Enlace (Drive, YouTube, etc.)"
        TEXTO = "TEXTO", "Aviso / texto"

    asignacion = models.ForeignKey(Asignacion, on_delete=models.CASCADE, related_name="materiales")
    titulo = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.ENLACE)
    enlace = models.URLField("Enlace", blank=True)
    contenido = models.TextField("Contenido / descripción", blank=True)
    fecha_publicacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Material de clase"
        verbose_name_plural = "Materiales de clase (Aula Virtual)"
        ordering = ["-fecha_publicacion"]

    def __str__(self):
        return f"{self.titulo} — {self.asignacion}"


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


class Convocatoria(models.Model):
    """Catálogo de convocatorias — son pocas y se repiten como filtro en cada
    postulante, así que se manejan aparte en vez de escribirlas a mano cada
    vez (evita variantes tipo '2026-II' vs '2026 - II' vs 'II-2026').

    Cada convocatoria trae su propia lista de unidades didácticas (plazas) —
    varían de una convocatoria a otra y no siempre coinciden con el catálogo
    general de Cursos, así que se cargan aparte (ver UnidadDidacticaConvocatoria)
    en vez de reutilizar ese catálogo."""

    nombre = models.CharField(max_length=100, unique=True, help_text="Ej. 2026-II, Semestre I 2026, etc.")
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Convocatoria"
        verbose_name_plural = "Convocatorias"
        ordering = ["-fecha_inicio", "nombre"]

    def __str__(self):
        return self.nombre


class UnidadDidacticaConvocatoria(models.Model):
    """Una plaza/unidad didáctica ofrecida en una Convocatoria específica —
    tal como aparece en el documento real de la convocatoria (nombre,
    especialidad funcional y perfil profesional exigido), no el catálogo
    general de Cursos usado para horarios."""

    convocatoria = models.ForeignKey(Convocatoria, on_delete=models.CASCADE, related_name="unidades_didacticas")
    nombre = models.CharField(max_length=200)
    especialidad_funcional = models.CharField(
        max_length=150, blank=True,
        help_text="Ej. Orden Público y Seguridad, Investigación Criminal, o en blanco si es común.",
    )
    perfil_profesional = models.TextField(
        blank=True, help_text="Requisitos de perfil tal como figuran en la convocatoria (opcional, solo referencia).",
    )

    class Meta:
        verbose_name = "Unidad didáctica de la convocatoria"
        verbose_name_plural = "Unidades didácticas de la convocatoria"
        ordering = ["convocatoria", "especialidad_funcional", "nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.convocatoria})"


class CriterioPuntaje(models.Model):
    """Escala de puntos de la Evaluación Curricular, editable — en vez de
    tener fijo el Anexo 10 o el Anexo 13, cada renglón (título profesional,
    maestría, doctorado, etc.) tiene su propio puntaje por unidad y su tope,
    así se puede combinar/ajustar libremente sin tocar código."""

    class Bloque(models.IntegerChoices):
        GRADOS_TITULOS = 1, "1. Grados académicos y títulos profesionales"
        CAPACITACIONES = 2, "2. Actualizaciones y capacitaciones afines"
        EVENTOS_INVESTIGACION = 3, "3. Participación en eventos científicos e investigación"
        OTROS_PROGRAMAS = 4, "4. Otros programas de formación continua"
        EXPERIENCIA_DOCENTE = 5, "5. Experiencia docente universitaria"
        EXPERIENCIA_PROFESIONAL = 6, "6. Experiencia profesional"

    clave = models.SlugField(
        max_length=50, unique=True,
        help_text="Identificador técnico — debe coincidir con el campo del postulante que puntúa. No cambiarlo.",
    )
    etiqueta = models.CharField(max_length=200)
    bloque = models.PositiveSmallIntegerField(choices=Bloque.choices)
    orden = models.PositiveSmallIntegerField(default=0)
    puntaje_por_unidad = models.DecimalField(
        "Puntaje por unidad", max_digits=4, decimal_places=2,
        help_text="Para casillas (sí/no) es el puntaje que se da una sola vez. Para conteos, el puntaje c/u.",
    )
    tope = models.DecimalField(
        "Puntaje máximo (tope)", max_digits=4, decimal_places=2,
        help_text="Puntaje máximo que puede aportar este criterio, sin importar cuántas unidades se registren.",
    )

    class Meta:
        verbose_name = "Criterio de puntaje"
        verbose_name_plural = "Criterios de puntaje (escala de calificación)"
        ordering = ["bloque", "orden"]

    def __str__(self):
        return f"{self.etiqueta} ({self.puntaje_por_unidad} c/u, tope {self.tope})"


class Postulante(models.Model):
    """Calificación de postulantes a la docencia — Manual del Personal Docente
    de la ENFPP PNP (RD N°022-2022-ENFPP-PNP), Cap. III-B y Anexos 10 a 13.
    Es para la EESTP PNP CUSCO exclusivamente (única escuela que maneja este
    sistema) — por eso no hay un campo de "escuela" para elegir.

    Puntaje Total = Evaluación Curricular + Capacidad Docente + Entrevista
    Personal. Las tres etapas son eliminatorias, con puntaje mínimo propio
    cada una (ver Anexo 10, cuadro de puntajes mínimos/máximos). La
    Evaluación Curricular (revisión de expediente) se suele calificar el
    mismo día que se recibe la documentación; Capacidad Docente y Entrevista
    Personal se hacen otro día — por eso esos bloques no son obligatorios
    para guardar el registro."""

    class Procedencia(models.TextChoices):
        PNP = "PNP", "PNP"
        FFAA = "FFAA", "Fuerzas Armadas"
        CIVIL = "CIVIL", "Civil"
        EXTRANJERO = "EXTRANJERO", "Extranjero"

    class Grado(models.TextChoices):
        # -- Personal policial/militar (PNP, FFAA) — abreviaturas de uso
        # oficial, para que el desplegable se lea de un vistazo. --
        GENERAL = "GENERAL", "Gral."
        CORONEL = "CORONEL", "Cnel."
        COMANDANTE = "COMANDANTE", "Cmdt."
        MAYOR = "MAYOR", "My."
        CAPITAN = "CAPITAN", "Cap."
        TENIENTE = "TENIENTE", "Tte."
        ALFEREZ = "ALFEREZ", "Alf."
        SO_SUPERIOR = "SO_SUPERIOR", "SOS"
        SO_BRIGADIER = "SO_BRIGADIER", "SOB"
        SOT1 = "SOT1", "SOT1"
        SOT2 = "SOT2", "SOT2"
        SOT3 = "SOT3", "SOT3"
        SO1 = "SO1", "S1"
        SO2 = "SO2", "S2"
        SO3 = "SO3", "S3"
        # -- Civil / Extranjero (grado académico o título) --
        CIVIL = "CIVIL", "Civil"
        TECNICO = "TECNICO", "Técnico"
        BACHILLER = "BACHILLER", "Bach."
        LICENCIADO = "LICENCIADO", "Lic."
        INGENIERO = "INGENIERO", "Ing."
        ABOGADO = "ABOGADO", "Abg."
        MAGISTER = "MAGISTER", "Mg."
        DOCTOR = "DOCTOR", "Dr."
        OTRO = "OTRO", "Otro"

    # Un policía o militar SÍ puede tener además un grado académico (p. ej. un
    # Mayor PNP con maestría) — eso se registra aparte en "Grados académicos y
    # títulos" (más abajo), no reemplaza su grado policial en este campo. Esta
    # lista solo sirve para que el desplegable de Grado muestre las opciones
    # que corresponden según la Procedencia elegida (ver admin_postulante.js).
    GRADOS_PNP_FFAA = [
        Grado.GENERAL, Grado.CORONEL, Grado.COMANDANTE, Grado.MAYOR, Grado.CAPITAN,
        Grado.TENIENTE, Grado.ALFEREZ, Grado.SO_SUPERIOR, Grado.SO_BRIGADIER,
        Grado.SOT1, Grado.SOT2, Grado.SOT3, Grado.SO1, Grado.SO2, Grado.SO3,
    ]
    GRADOS_CIVIL = [
        Grado.CIVIL, Grado.TECNICO, Grado.BACHILLER, Grado.LICENCIADO,
        Grado.INGENIERO, Grado.ABOGADO, Grado.MAGISTER, Grado.DOCTOR, Grado.OTRO,
    ]

    # --- Datos generales (Anexo 06) ---
    apellidos = models.CharField(max_length=150)
    nombres = models.CharField(max_length=150)
    dni = models.CharField("DNI", max_length=15, blank=True)
    cip = models.CharField("CIP", max_length=15, blank=True, help_text="Opcional — solo aplica a personal PNP.")
    celular = models.CharField("Telf. celular", max_length=20, blank=True)
    grado = models.CharField(max_length=15, choices=Grado.choices, default=Grado.CIVIL)
    procedencia = models.CharField(max_length=12, choices=Procedencia.choices, default=Procedencia.CIVIL)
    unidad_didactica = models.ForeignKey(
        UnidadDidacticaConvocatoria, on_delete=models.PROTECT, related_name="postulantes",
        verbose_name="Unidad didáctica a la que postula",
    )
    convocatoria = models.ForeignKey(
        Convocatoria, on_delete=models.PROTECT, related_name="postulantes",
    )
    postula_a_otro_curso_misma_convocatoria = models.BooleanField(
        "También postula a otro curso en esta misma convocatoria",
        default=False,
        help_text="Márcalo si esta misma persona tiene otro registro de postulante en esta convocatoria "
        "(para otra unidad didáctica) — sirve para el listado por curso que se hará más adelante.",
    )
    fecha_evaluacion = models.DateField(null=True, blank=True)
    docente = models.ForeignKey(
        "Docente", on_delete=models.SET_NULL, null=True, blank=True, related_name="postulaciones",
        help_text="Se detecta solo por DNI al guardar, si ya existe un Docente con ese mismo DNI. "
        "También puedes seleccionarlo a mano si hace falta — nunca se vincula por nombre parecido.",
    )

    # --- Evaluación Curricular — bloque 1: Grados y Títulos (máx. 20) ---
    # Las 4 líneas de acá son exactamente las de la Hoja de Vida oficial
    # (Evaluación de la Hoja de Vida de Postulantes a Plaza de Docentes):
    # cada una es una sola casilla con un solo puntaje, no hay que elegir
    # variante ni Anexo — el propio enunciado ya cubre ambos casos.
    tiene_titulo_profesional = models.BooleanField(
        "Título Profesional en Administración y Ciencias Policiales", default=False
    )
    tiene_titulo_tecnico_o_civil = models.BooleanField(
        "Título profesional Técnico en ciencias policiales / profesional civil", default=False
    )
    tiene_maestria_o_doctorado = models.BooleanField("Grado académico de Maestro/Doctor", default=False)
    tiene_segunda_especialidad = models.BooleanField(
        "Segunda Especialidad o Título de Especialista de acuerdo a la naturaleza de la UD", default=False
    )

    # --- bloque 2: Actualizaciones y capacitaciones afines (máx. 3) ---
    # Los campos de cantidad de los bloques 2 a 6 admiten decimales (p. ej.
    # 0.5 ciclos o 1.5 cursos) — el puntaje por unidad de varios criterios
    # ya es fraccionario (0.5), así que la cantidad digitada también debe
    # poder serlo (media hora dictada, medio curso, etc.).
    diplomados_120h = models.DecimalField(
        "Diplomados afines ≥120h (1.0 c/u, tope 2)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    programas_16_96h_afines = models.DecimalField(
        "Programas afines 16-96h (0.5 c/u, tope 2)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )

    # --- bloque 3: Participación en eventos científicos e investigación (máx. 3) ---
    ponente_eventos = models.DecimalField(
        "Ponente en eventos académicos (0.5 c/u, tope 1)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    asistente_eventos = models.DecimalField(
        "Asistente a eventos académicos (0.5 c/u, tope 1)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    investigaciones = models.DecimalField(
        "Investigaciones en la especialidad (1.0 c/u, tope 1)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    publicaciones = models.DecimalField(
        "Textos y/o libros publicados (1.0 c/u, tope 1)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )

    # --- bloque 4: Otros programas de formación continua (máx. 4) ---
    programas_96h_otros = models.DecimalField(
        "Programas ≥96h (1.0 c/u, tope 2)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    programas_16_96h_otros = models.DecimalField(
        "Programas 16-96h (0.5 c/u, tope 2)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    cursos_ofimatica_24h = models.DecimalField(
        "Cursos de ofimática ≥24h (0.5 c/u, tope 2)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )

    # --- bloque 5: Experiencia docente universitaria (máx. 4) ---
    pregrado_ciclos = models.DecimalField(
        "Docencia nivel pregrado, en ciclos (0.5 c/ciclo)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    maestria_cursos = models.DecimalField(
        "Docencia posgrado Maestría, en cursos (0.5 c/curso, tope 1)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )

    # --- bloque 6: Experiencia profesional (máx. 6) ---
    experiencia_profesional_anios = models.DecimalField(
        "Ejercicio profesional no docente, en años (1.0 c/año, tope 6)",
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
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
    observaciones_entrevista = models.TextField(
        "Observaciones de la Entrevista Personal", blank=True,
    )

    class Meta:
        verbose_name = "Postulante (calificación docente)"
        verbose_name_plural = "Postulantes (calificación docente)"
        ordering = ["convocatoria", "unidad_didactica", "apellidos", "nombres"]

    def __str__(self):
        return f"{self.nombre_completo} — {self.unidad_didactica} ({self.convocatoria})"

    @property
    def nombre_completo(self):
        return f"{self.apellidos} {self.nombres}".strip()

    def save(self, *args, **kwargs):
        # Si el DNI coincide con un Docente ya existente, se vincula solo —
        # sin checkbox ni acción manual. Esto NO crea ni actualiza el
        # Docente (eso sigue reservado a vincular_o_crear_docente, que solo
        # corre cuando el postulante ya ganó); solo evita que jefatura tenga
        # que acordarse de buscarlo y seleccionarlo a mano cada vez.
        if not self.docente_id and self.dni:
            coincidencia = Docente.objects.filter(dni=self.dni).first()
            if coincidencia:
                self.docente = coincidencia
        super().save(*args, **kwargs)
        # Deja (o actualiza) un registro en Persona con estos mismos datos,
        # para que la próxima vez que jefatura digite este DNI —en este
        # postulante o en cualquier otro— los datos aparezcan solos. Es un
        # registro aparte, nunca toca la ficha de Docente.
        if self.dni:
            Persona.objects.update_or_create(
                dni=self.dni,
                defaults={
                    "apellidos": self.apellidos,
                    "nombres": self.nombres,
                    "cip": self.cip,
                    "celular": self.celular,
                    "procedencia": self.procedencia,
                    "grado": self.grado,
                },
            )

    # --- Puntajes calculados ---
    # El puntaje por unidad y el tope de cada criterio salen de
    # CriterioPuntaje (editable en el admin) — así se puede combinar o
    # ajustar libremente la escala del Anexo 10/13 sin tocar código. Si un
    # criterio todavía no está configurado, se usa el valor por defecto
    # (el mismo del Anexo 13) para que nada se rompa antes de cargar la
    # escala real.

    _DEFAULTS_CRITERIOS = {
        # Estos 4 puntajes son los de la Hoja de Vida oficial (Evaluación
        # de la Hoja de Vida de Postulantes a Plaza de Docentes): 5+4+6+5=20.
        "tiene_titulo_profesional": (5.0, 5.0),
        "tiene_titulo_tecnico_o_civil": (4.0, 4.0),
        "tiene_maestria_o_doctorado": (6.0, 6.0),
        "tiene_segunda_especialidad": (5.0, 5.0),
        "diplomados_120h": (1.0, 2.0),
        "programas_16_96h_afines": (0.5, 1.0),
        "ponente_eventos": (0.5, 0.5),
        "asistente_eventos": (0.5, 0.5),
        "investigaciones": (1.0, 1.0),
        "publicaciones": (1.0, 1.0),
        "programas_96h_otros": (1.0, 2.0),
        "programas_16_96h_otros": (0.5, 1.0),
        "cursos_ofimatica_24h": (0.5, 1.0),
        "pregrado_ciclos": (0.5, 3.0),
        "maestria_cursos": (0.5, 1.0),
        "experiencia_profesional_anios": (1.0, 6.0),
    }

    @classmethod
    def criterio(cls, clave):
        """Devuelve (puntaje_por_unidad, tope) para un criterio — desde la
        base si ya está configurado, si no, el valor por defecto."""
        fila = CriterioPuntaje.objects.filter(clave=clave).first()
        if fila:
            return float(fila.puntaje_por_unidad), float(fila.tope)
        return cls._DEFAULTS_CRITERIOS[clave]

    def _puntos(self, clave, cantidad):
        unidad, tope = self.criterio(clave)
        return min(float(cantidad) * unidad, tope)

    def puntaje_grados_titulos(self):
        total = 0
        if self.tiene_titulo_profesional:
            total += self._puntos("tiene_titulo_profesional", 1)
        if self.tiene_titulo_tecnico_o_civil:
            total += self._puntos("tiene_titulo_tecnico_o_civil", 1)
        if self.tiene_maestria_o_doctorado:
            total += self._puntos("tiene_maestria_o_doctorado", 1)
        if self.tiene_segunda_especialidad:
            total += self._puntos("tiene_segunda_especialidad", 1)
        return total

    def puntaje_capacitaciones(self):
        return self._puntos("diplomados_120h", self.diplomados_120h) + self._puntos(
            "programas_16_96h_afines", self.programas_16_96h_afines
        )

    def puntaje_eventos_investigacion(self):
        return (
            self._puntos("ponente_eventos", self.ponente_eventos)
            + self._puntos("asistente_eventos", self.asistente_eventos)
            + self._puntos("investigaciones", self.investigaciones)
            + self._puntos("publicaciones", self.publicaciones)
        )

    def puntaje_otros_programas(self):
        return (
            self._puntos("programas_96h_otros", self.programas_96h_otros)
            + self._puntos("programas_16_96h_otros", self.programas_16_96h_otros)
            + self._puntos("cursos_ofimatica_24h", self.cursos_ofimatica_24h)
        )

    def puntaje_experiencia_docente(self):
        return self._puntos("pregrado_ciclos", self.pregrado_ciclos) + self._puntos(
            "maestria_cursos", self.maestria_cursos
        )

    def puntaje_experiencia_profesional(self):
        return self._puntos("experiencia_profesional_anios", self.experiencia_profesional_anios)

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

    @classmethod
    def maximo_bloque(cls, bloque):
        """Suma de topes configurados para un bloque — si nada está
        configurado todavía, suma los valores por defecto de ese bloque."""
        claves_por_bloque = {
            1: ["tiene_titulo_profesional", "tiene_titulo_tecnico_o_civil", "tiene_maestria_o_doctorado", "tiene_segunda_especialidad"],
            2: ["diplomados_120h", "programas_16_96h_afines"],
            3: ["ponente_eventos", "asistente_eventos", "investigaciones", "publicaciones"],
            4: ["programas_96h_otros", "programas_16_96h_otros", "cursos_ofimatica_24h"],
            5: ["pregrado_ciclos", "maestria_cursos"],
            6: ["experiencia_profesional_anios"],
        }
        return round(sum(cls.criterio(clave)[1] for clave in claves_por_bloque[bloque]), 2)

    @classmethod
    def maximo_evaluacion_curricular(cls):
        return round(sum(cls.maximo_bloque(b) for b in range(1, 7)), 2)

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
        if self.tiene_maestria_o_doctorado:
            return 2
        if self.tiene_titulo_profesional or self.tiene_titulo_tecnico_o_civil:
            return 1
        return 0

    def vincular_o_crear_docente(self):
        """Crea el Docente si es nuevo, o actualiza el ya vinculado — sin
        adivinar por nombre parecido. Si `self.docente` ya está seleccionado
        a mano, se actualiza ese. Si no, se busca una coincidencia exacta
        por DNI (identificador fuerte); si tampoco hay, se crea uno nuevo.
        Solo procede si el postulante ya aprobó las 3 etapas y quedó como
        ganador — mientras siga en evaluación no corresponde darlo de alta
        como Docente. Devuelve (docente, creado: bool)."""
        if not self.resultado().startswith("GANADOR"):
            raise ValueError(
                "Este postulante todavía no está calificado y aceptado como ganador "
                f"(resultado actual: {self.resultado()})."
            )

        docente = self.docente
        if docente is None and self.dni:
            docente = Docente.objects.filter(dni=self.dni).first()

        creado = False
        if docente is None:
            if not self.dni:
                raise ValueError(
                    "No se puede crear el Docente sin DNI — complétalo en el postulante primero."
                )
            docente = Docente(
                apellidos_nombres=self.nombre_completo,
                dni=self.dni,
                id_biometrico=self.dni,
                grado=self.get_grado_display(),
                celular=self.celular,
                estado=Docente.Estado.ACTIVO,
                fecha_ingreso=self.fecha_evaluacion,
            )
            creado = True
        else:
            if not docente.dni and self.dni:
                docente.dni = self.dni
            if self.grado:
                docente.grado = self.get_grado_display()
            if self.celular:
                docente.celular = self.celular

        docente.save()

        if self.docente_id != docente.id:
            self.docente = docente
            self.save(update_fields=["docente"])

        return docente, creado


class Persona(models.Model):
    """Registro de referencia por DNI, para autocompletar el formulario de
    Postulante — sea o no esa persona Docente. Se llena solo cada vez que
    se guarda un Postulante con DNI (ver Postulante.save()); también se
    puede cargar o corregir a mano acá. Es una tabla aparte, nunca se
    cruza ni se sincroniza con Docente — evita que buscar por DNI toque o
    dependa de la ficha de Docente."""

    dni = models.CharField("DNI", max_length=15, unique=True)
    apellidos = models.CharField(max_length=150)
    nombres = models.CharField(max_length=150)
    cip = models.CharField("CIP", max_length=15, blank=True, help_text="Opcional — solo aplica a personal PNP.")
    celular = models.CharField("Telf. celular", max_length=20, blank=True)
    procedencia = models.CharField(max_length=12, choices=Postulante.Procedencia.choices, blank=True)
    grado = models.CharField(max_length=15, choices=Postulante.Grado.choices, blank=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Persona (referencia de búsqueda por DNI)"
        verbose_name_plural = "Personas (referencia de búsqueda por DNI)"
        ordering = ["apellidos", "nombres"]

    def __str__(self):
        return f"{self.apellidos} {self.nombres} ({self.dni})"
