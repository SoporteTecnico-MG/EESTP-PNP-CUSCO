(function () {
    function filtrarSelectMulti(select, condiciones) {
        // condiciones: array de {attr, valor} — todas deben cumplirse para mostrar la opción.
        // valor vacío/null en una condición significa "sin filtrar por ese atributo".
        if (!select) return;
        let valido = false;
        Array.from(select.options).forEach(function (opt) {
            if (!opt.value) {
                opt.hidden = false;
                return;
            }
            let visible = true;
            condiciones.forEach(function (c) {
                if (!c.valor) return;
                const ok = c.permitirVacio
                    ? (opt.dataset[c.attr] === "" || opt.dataset[c.attr] === c.valor)
                    : opt.dataset[c.attr] === c.valor;
                if (!ok) visible = false;
            });
            opt.hidden = !visible;
            if (opt.selected && !visible) opt.selected = false;
            if (opt.selected && visible) valido = true;
        });
        if (!valido) select.value = "";
    }

    function initFila(fila) {
        if (!fila || fila.dataset.cascadaInit) return;
        const promocionSel = fila.querySelector('[data-role="promocion-filtro"]');
        const periodoSel = fila.querySelector('[data-role="periodo-filtro"]');
        const aulaSel = fila.querySelector('[data-role="aula-select"]');
        const ofertaSel = fila.querySelector('[data-role="oferta-select"]');
        if (!promocionSel || !periodoSel || !aulaSel || !ofertaSel) return;
        fila.dataset.cascadaInit = "1";

        // Al editar una fila ya guardada, deducir los filtros desde los valores actuales.
        if (aulaSel.value && !promocionSel.value) {
            const opt = aulaSel.querySelector('option[value="' + aulaSel.value + '"]');
            if (opt && opt.dataset.promocion) {
                promocionSel.value = opt.dataset.promocion;
            }
        }
        if (ofertaSel.value && !periodoSel.value) {
            const opt = ofertaSel.querySelector('option[value="' + ofertaSel.value + '"]');
            if (opt && opt.dataset.periodo) {
                periodoSel.value = opt.dataset.periodo;
            }
        }

        function especialidadAula() {
            const opt = aulaSel.querySelector('option[value="' + aulaSel.value + '"]');
            return opt ? opt.dataset.especialidad : "";
        }

        function aplicarOferta() {
            filtrarSelectMulti(ofertaSel, [
                { attr: "periodo", valor: periodoSel.value },
                { attr: "especialidad", valor: especialidadAula(), permitirVacio: true },
            ]);
        }

        function aplicarPromocion() {
            filtrarSelectMulti(aulaSel, [{ attr: "promocion", valor: promocionSel.value }]);
            filtrarSelectMulti(periodoSel, [{ attr: "promocion", valor: promocionSel.value }]);
            aplicarOferta();
        }

        promocionSel.addEventListener("change", aplicarPromocion);
        periodoSel.addEventListener("change", aplicarOferta);
        aulaSel.addEventListener("change", aplicarOferta);

        aplicarPromocion();
    }

    function initTodas() {
        document
            .querySelectorAll("tr.form-row:not(.empty-form), .inline-related:not(.empty-form)")
            .forEach(initFila);
    }

    document.addEventListener("DOMContentLoaded", initTodas);

    if (window.django && django.jQuery) {
        django.jQuery(document).on("formset:added", function (event, row) {
            initFila(row[0] || row);
        });
    }
})();
