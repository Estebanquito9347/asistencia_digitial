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
                        <strong>${curso}</strong>
                        <label>Hora de entrada
                            <input type="time" id="hora-${curso}" value="${cfg.hora_entrada}">
                        </label>
                        <label>Tolerancia (min)
                            <input type="number" id="tolerancia-${curso}" value="${cfg.tolerancia_minutos}" min="0" max="120">
                        </label>
                        <button onclick="guardarHorario('${curso}')">Guardar</button>
                    </div>
                `;
            }).join('');
        })
        .catch(err => console.error('Error al cargar horarios:', err));
}

function guardarHorario(curso) {
    const hora_entrada = document.getElementById(`hora-${curso}`).value;
    const tolerancia_minutos = document.getElementById(`tolerancia-${curso}`).value;

    fetch('/admin/api/horarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ curso, hora_entrada, tolerancia_minutos })
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