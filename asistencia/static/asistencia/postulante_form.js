(function () {
    function initProcedenciaGrado() {
        const procedencia = document.querySelector('[data-role="procedencia-select"]');
        const grado = document.querySelector('[data-role="grado-select"]');
        if (!procedencia || !grado) return;

        function grupoDe(valor) {
            return (valor === "PNP" || valor === "FFAA") ? "PNP_FFAA" : "CIVIL";
        }

        function aplicar() {
            const grupo = grupoDe(procedencia.value);
            let valido = false;
            Array.from(grado.options).forEach(function (opt) {
                if (!opt.value) { opt.hidden = false; return; }
                const visible = opt.dataset.procedencia === grupo;
                opt.hidden = !visible;
                if (opt.selected && !visible) opt.selected = false;
                if (opt.selected && visible) valido = true;
            });
            if (!valido) grado.value = "";
        }

        procedencia.addEventListener("change", aplicar);
        aplicar();
    }

    function fmt(n) {
        return n.toFixed(2);
    }

    function initCalculadoraPuntos() {
        const criterios = window.CRITERIOS_PUNTAJE;
        if (!criterios) return;
        const claves = Object.keys(criterios);

        const total = document.createElement("div");
        total.id = "pd-total-flotante";
        total.innerHTML = '<span>Evaluación Curricular (en vivo)</span><span class="num"></span>';
        const primerFieldset = document.querySelector("fieldset.module.aligned");
        if (primerFieldset && primerFieldset.parentNode) {
            primerFieldset.parentNode.insertBefore(total, primerFieldset);
        }
        const totalNum = total.querySelector(".num");
        const maximoTotal = claves.reduce(function (acc, k) { return acc + criterios[k].tope; }, 0);

        function badgeDe(campo) {
            let badge = campo._pdBadge;
            if (badge) return badge;
            badge = document.createElement("span");
            badge.className = "pd-badge";
            const contenedor = campo.closest(".flex-container") || campo.parentNode;
            contenedor.appendChild(badge);
            campo._pdBadge = badge;
            return badge;
        }

        function recalcular() {
            let sumaTotal = 0;
            claves.forEach(function (clave) {
                const campo = document.getElementById("id_" + clave);
                if (!campo) return;
                const cfg = criterios[clave];
                let puntos = 0;
                if (campo.type === "checkbox") {
                    puntos = campo.checked ? Math.min(cfg.unidad, cfg.tope) : 0;
                } else {
                    const cantidad = parseFloat(campo.value) || 0;
                    puntos = Math.min(cantidad * cfg.unidad, cfg.tope);
                }
                sumaTotal += puntos;
                const badge = badgeDe(campo);
                badge.textContent = fmt(puntos) + " / " + fmt(cfg.tope);
                badge.classList.toggle("pd-badge-tope", puntos >= cfg.tope && cfg.tope > 0);
            });
            totalNum.textContent = fmt(sumaTotal) + " / " + fmt(maximoTotal);
        }

        claves.forEach(function (clave) {
            const campo = document.getElementById("id_" + clave);
            if (!campo) return;
            campo.addEventListener("input", recalcular);
            campo.addEventListener("change", recalcular);
        });

        recalcular();
    }

    function initBusquedaDni() {
        const dni = document.querySelector('[data-role="dni-input"]');
        if (!dni || !window.BUSCAR_POSTULANTE_URL) return;

        const envoltorio = dni.parentNode;
        const fila = document.createElement("div");
        fila.className = "pd-dni-fila";
        dni.insertAdjacentElement("afterend", fila);

        const boton = document.createElement("button");
        boton.type = "button";
        boton.className = "pd-dni-buscar";
        boton.textContent = "Buscar";
        fila.appendChild(boton);

        const aviso = document.createElement("span");
        aviso.className = "pd-dni-aviso";
        envoltorio.appendChild(aviso);

        function llenar(campo, valor) {
            const el = document.getElementById("id_" + campo);
            if (el && !el.value && valor) el.value = valor;
        }

        function buscar() {
            const valor = dni.value.trim();
            aviso.textContent = "";
            aviso.className = "pd-dni-aviso";
            if (valor.length < 6) {
                aviso.textContent = "Escribe el DNI completo y presiona Buscar.";
                return;
            }
            aviso.textContent = "Buscando…";
            fetch(window.BUSCAR_POSTULANTE_URL + "?dni=" + encodeURIComponent(valor))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!data.encontrado) {
                        aviso.textContent = "No hay ningún registro con ese DNI — completa los datos para crear uno nuevo.";
                        aviso.className = "pd-dni-aviso pd-dni-aviso-nuevo";
                        return;
                    }
                    llenar("apellidos", data.apellidos);
                    llenar("nombres", data.nombres);
                    llenar("cip", data.cip);
                    llenar("celular", data.celular);
                    const procedencia = document.getElementById("id_procedencia");
                    if (procedencia && data.procedencia) {
                        procedencia.value = data.procedencia;
                        procedencia.dispatchEvent(new Event("change"));
                    }
                    llenar("grado", data.grado);
                    aviso.textContent = "Datos encontrados — se completaron los campos vacíos.";
                    aviso.className = "pd-dni-aviso pd-dni-aviso-ok";
                });
        }

        dni.addEventListener("blur", buscar);
        boton.addEventListener("click", buscar);
        dni.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter") {
                ev.preventDefault();
                buscar();
            }
        });
    }

    function initOcultarPanelLateral() {
        // Este formulario tiene muchos campos — se oculta el panel de
        // navegación la primera vez que se abre, para dejar toda la
        // pantalla disponible para editar. El botón "»" de siempre lo
        // vuelve a mostrar si hace falta.
        if (sessionStorage.getItem("pd-panel-ocultado")) return;
        const boton = document.querySelector("#toggle-nav-sidebar");
        const sidebar = document.querySelector("#nav-sidebar");
        if (!boton || !sidebar || sidebar.getBoundingClientRect().width === 0) return;
        boton.click();
        sessionStorage.setItem("pd-panel-ocultado", "1");
    }

    document.addEventListener("DOMContentLoaded", function () {
        initProcedenciaGrado();
        initCalculadoraPuntos();
        initBusquedaDni();
        initOcultarPanelLateral();
    });
})();
