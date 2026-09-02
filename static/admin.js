// static/admin.js
// -----------------
// Panel de la preceptora: resumen y registros por curso, edición de
// horarios, descarga de CSV por curso.

const statusAdmin = document.getElementById('statusAdmin');
const filtroCurso = document.getElementById('filtroCurso');

cargarCursosEnFiltro();
cargarResumen();
cargarRegistros();
cargarHorarios();
setInterval(() => { cargarResumen(); cargarRegistros(); }, 10000);

filtroCurso.addEventListener('change', cargarRegistros);

function cargarCursosEnFiltro() {
    fetch('/obtener_cursos')
        .then(res => res.json())
        .then(data => {
            (data.cursos || []).forEach(curso => {
                const option = document.createElement('option');
                option.value = curso;
                option.innerText = curso;
                filtroCurso.appendChild(option);
            });
            cargarContraturnos();
        })
        .catch(err => console.error('Error al cargar cursos:', err));
}

function cargarResumen() {
    fetch('/admin/api/resumen')
        .then(res => res.json())
        .then(data => {
            const contenedor = document.getElementById('resumenCursos');
            if (!data.cursos || data.cursos.length === 0) {
                contenedor.innerHTML = '<em>Todavía no hay presentes registrados hoy.</em>';
                return;
            }
            contenedor.innerHTML = data.cursos
                .map(c => `<div class="resumen-fila"><span>${c.curso}</span><strong>${c.presentes}</strong></div>`)
                .join('');
        })
        .catch(err => console.error('Error al cargar resumen:', err));
}

function cargarRegistros() {
    const curso = filtroCurso.value;
    const url = curso ? `/admin/api/registros?curso=${encodeURIComponent(curso)}` : '/admin/api/registros';

    fetch(url)
        .then(res => res.json())
        .then(data => {
            const tabla = document.getElementById('tablaRegistros');
            if (!data.registros || data.registros.length === 0) {
                tabla.innerHTML = '<tr><td colspan="4"><em>Sin registros hoy.</em></td></tr>';
                return;
            }
            tabla.innerHTML = data.registros.map(r => `
                <tr>
                    <td>${r.Hora}</td>
                    <td>${r.Alumno}</td>
                    <td>${r.Curso}</td>
                    <td>${r.Estado === 'TARDE' ? '⏰ TARDE' : '✅ PRESENTE'}</td>
                </tr>
            `).join('');
        })
        .catch(err => console.error('Error al cargar registros:', err));
}

function cargarHorarios() {
    fetch('/admin/api/horarios')
        .then(res => res.json())
        .then(data => {
            const contenedor = document.getElementById('listaHorarios');
            const cursos = Object.keys(data.horarios || {}).sort();

            if (cursos.length === 0) {
                contenedor.innerHTML = '<em>No hay cursos en la carpeta rostros/.</em>';
                return;
            }

            contenedor.innerHTML = cursos.map(curso => {
                const cfg = data.horarios[curso];
                return `
                    <div class="control-group horario-fila">
                        <div class="horario-curso"><strong>${curso}</strong>
                            ${cfg.modificado_hoy ? '<small>⚠️ Cambio aplicado hoy</small>' : ''}
                        </div>
                        <label>Habitual
                            <input type="time" id="hora-habitual-${curso}" value="${cfg.hora_habitual}">
                        </label>
                        <label>Tolerancia
                            <input type="number" id="tolerancia-habitual-${curso}" value="${cfg.tolerancia_habitual}" min="0" max="120">
                        </label>
                        <button onclick="guardarHorario('${curso}', true)">Guardar habitual</button>
                        <label>Entrada de hoy
                            <input type="time" id="hora-hoy-${curso}" value="${cfg.hora_entrada}">
                        </label>
                        <label>Tolerancia
                            <input type="number" id="tolerancia-hoy-${curso}" value="${cfg.tolerancia_minutos}" min="0" max="120">
                        </label>
                        <button class="btn-success" onclick="guardarHorario('${curso}', false)">Modificar hoy</button>
                    </div>
                `;
            }).join('');

        })
        .catch(err => console.error('Error al cargar horarios:', err));
}

function cargarContraturnos() {
    fetch('/admin/api/contraturnos')
        .then(res => res.json())
        .then(data => {
            const cursos = [...filtroCurso.options].filter(o => o.value).map(o => o.value).sort();
            const selector = document.getElementById('contraturnoCurso');
            selector.innerHTML = cursos.map(c => `<option value="${c}">${c}</option>`).join('');
            
            const lista = document.getElementById('listaContraturnos');
            const contraturnos = data.contraturnos || [];

            if (contraturnos.length === 0) {
                lista.innerHTML = '<em>No hay contraturnos cargados.</em>';
                return;
            }

            // Agrupar contraturnos por curso
            const porCurso = {};
            contraturnos.forEach(r => {
                if (!porCurso[r.curso]) porCurso[r.curso] = [];
                porCurso[r.curso].push(r);
            });

            // Renderizar estructura expandible por curso
            lista.innerHTML = Object.keys(porCurso).sort().map(curso => {
                const id_expandible = `contraturnos-${curso.replace(/\s+/g, '-')}`;
                return `
                    <div class="contraturno-curso">
                        <button type="button" class="btn-expandible" onclick="toggleExpandible('${id_expandible}')">
                            ▶ ${curso}
                        </button>
                        <div id="${id_expandible}" class="contraturno-contenido" style="display:none;">
                            ${porCurso[curso].map(r => `
                                <div class="contraturno-registro">
                                    <span class="contraturno-dia">${r.dia}</span>
                                    <span class="contraturno-hora">${r.hora_entrada}</span>
                                    <span class="contraturno-tolerancia">(${r.tolerancia_minutos} min)</span>
                                    <button type="button" onclick="editarContraturno('${r.id}', '${r.curso}', '${r.dia}', '${r.hora_entrada}', ${r.tolerancia_minutos})">Editar</button>
                                    <button type="button" class="btn-success" onclick="activarContraturno('${r.id}', '${r.curso}')">Usar hoy</button>
                                    <button type="button" class="btn-danger" onclick="eliminarContraturno('${r.id}', '${r.curso}')">Eliminar</button>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;
            }).join('');
        })
        .catch(err => console.error('Error al cargar contraturnos:', err));
}

function toggleExpandible(id) {
    const elemento = document.getElementById(id);
    if (elemento) {
        elemento.style.display = elemento.style.display === 'none' ? 'block' : 'none';
        // Cambiar ícono del botón
        const boton = elemento.previousElementSibling;
        if (boton) {
            boton.textContent = boton.textContent.startsWith('▶')
                ? boton.textContent.replace('▶', '▼')
                : boton.textContent.replace('▼', '▶');
        }
    }
}

function activarContraturno(id, curso) {
    fetch(`/admin/api/contraturnos/${encodeURIComponent(id)}/activar`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({curso})
    }).then(res => res.json()).then(data => {
        statusAdmin.innerText = data.ok ? `✅ Contraturno de ${curso} activado para hoy` : `❌ ${data.mensaje}`;
    });
}

document.getElementById('formContraturno').addEventListener('submit', event => {
    event.preventDefault();
    const datos = {
        curso: document.getElementById('contraturnoCurso').value,
        dia: document.getElementById('contraturnoDia').value,
        hora_entrada: document.getElementById('contraturnoHora').value,
        tolerancia_minutos: document.getElementById('contraturnoTolerancia').value
    };
    fetch('/admin/api/contraturnos', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(datos)
    }).then(res => res.json()).then(data => {
        statusAdmin.innerText = data.ok ? '✅ Contraturno agregado' : `❌ ${data.mensaje}`;
        if (data.ok) cargarContraturnos();
    });
});

function editarContraturno(id, curso, dia, hora, tolerancia) {
    const datos = {
        curso, dia: prompt('Día (lunes a viernes):', dia),
        hora_entrada: prompt('Hora de entrada (HH:MM):', hora),
        tolerancia_minutos: prompt('Tolerancia en minutos:', tolerancia)
    };
    if (!datos.dia || !datos.hora_entrada || datos.tolerancia_minutos === null) return;
    fetch(`/admin/api/contraturnos/${encodeURIComponent(id)}`, {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(datos)
    }).then(res => res.json()).then(data => {
        statusAdmin.innerText = data.ok ? '✅ Contraturno actualizado' : `❌ ${data.mensaje}`;
        if (data.ok) cargarContraturnos();
    });
}

function eliminarContraturno(id, curso) {
    if (!confirm(`¿Eliminar el contraturno de ${curso}?`)) return;
    fetch(`/admin/api/contraturnos/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({curso})
    })
    .then(res => res.json()).then(data => {
        statusAdmin.innerText = data.ok ? '✅ Contraturno eliminado' : `❌ ${data.mensaje}`;
        if (data.ok) cargarContraturnos();
    });
}

function guardarHorario(curso, guardar_habitual) {
    const sufijo = guardar_habitual ? 'habitual' : 'hoy';
    const hora_entrada = document.getElementById(`hora-${sufijo}-${curso}`).value;
    const tolerancia_minutos = document.getElementById(`tolerancia-${sufijo}-${curso}`).value;

    fetch('/admin/api/horarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ curso, hora_entrada, tolerancia_minutos, guardar_habitual })
    })
    .then(res => res.json())
    .then(data => {
        statusAdmin.innerText = data.ok
            ? `✅ Horario de ${curso} actualizado`
            : `❌ ${data.mensaje}`;
    })
    .catch(err => {
        console.error('Error al guardar horario:', err);
        statusAdmin.innerText = '❌ Error de conexión';
    });
}

function descargarCSV() {
    const curso = filtroCurso.value;
    if (!curso) {
        alert('Elegí un curso específico para descargar (arriba, en el filtro).');
        return;
    }
    window.location.href = `/admin/descargar_asistencia/${encodeURIComponent(curso)}`;
}

function reentrenar() {
    statusAdmin.innerText = '🔄 Reentrenando...';
    fetch('/admin/reentrenar_rostros', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    })
    .then(res => res.json())
    .then(data => {
        statusAdmin.innerText = `✅ Listo: ${data.alumnos_cargados} alumnos cargados`;
    })
    .catch(err => {
        console.error('Error al reentrenar:', err);
        statusAdmin.innerText = '❌ Error de conexión';
    });
}
