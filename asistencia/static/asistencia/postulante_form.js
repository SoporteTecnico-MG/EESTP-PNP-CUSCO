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

    document.addEventListener("DOMContentLoaded", function () {
        initProcedenciaGrado();
        initCalculadoraPuntos();
    });
})();
