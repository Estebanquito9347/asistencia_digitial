// static/admin.js
// -----------------
// Panel de la preceptora, rediseñado para ser simple: pestañas
// grandes, tarjetas por curso, y un acordeón para editar horarios
// sin tener que entender la estructura de datos de abajo.

const statusAdmin = document.getElementById('statusAdmin');

const DIAS = [
    { clave: 'lunes', letra: 'L' },
    { clave: 'martes', letra: 'M' },
    { clave: 'miercoles', letra: 'X' },
    { clave: 'jueves', letra: 'J' },
    { clave: 'viernes', letra: 'V' },
];

let listaCursos = [];
let cursoFiltroActual = null;
let registrosGlobales = []; // NUEVO: Guarda todos los registros de hoy
let filtroTurnoActual = 'todos'; // NUEVO: Filtro por tipo de asistencia ('todos', 'habitual', 'contraturno')

// ------------------------------------------------------------------
// Pestañas
// ------------------------------------------------------------------
function mostrarTab(nombre) {
    document.getElementById('tabAsistencia').style.display = nombre === 'asistencia' ? 'block' : 'none';
    document.getElementById('tabHorarios').style.display = nombre === 'horarios' ? 'block' : 'none';
    document.getElementById('tabBtnAsistencia').classList.toggle('activo', nombre === 'asistencia');
    document.getElementById('tabBtnHorarios').classList.toggle('activo', nombre === 'horarios');
}

// ------------------------------------------------------------------
// Arranque
// ------------------------------------------------------------------
mostrarFechaDeHoy();
cargarCursos();
cargarResumen();
cargarRegistros();
cargarHorarios();
setInterval(() => { cargarResumen(); cargarRegistros(); }, 10000);

function mostrarFechaDeHoy() {
    const dias = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
    const meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
                   'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
    const hoy = new Date();
    const texto = `Asistencia de hoy — ${dias[hoy.getDay()]} ${hoy.getDate()} de ${meses[hoy.getMonth()]}`;
    document.getElementById('fechaHoy').innerText = texto;
}

function cargarCursos() {
    fetch('/obtener_cursos')
        .then(res => res.json())
        .then(data => {
            listaCursos = data.cursos || [];
            document.getElementById('checkboxCursos').innerHTML = listaCursos.map(curso => `
                <label class="checkbox-curso">
                    <input type="checkbox" value="${curso}"> ${curso}
                </label>
            `).join('');
        })
        .catch(err => console.error('Error al cargar cursos:', err));
}

// ------------------------------------------------------------------
// TAB Asistencia
// ------------------------------------------------------------------
function cargarResumen() {
    fetch('/admin/api/resumen')
        .then(res => res.json())
        .then(data => {
            const contenedor = document.getElementById('tarjetasCursos');
            if (!data.cursos || data.cursos.length === 0) {
                contenedor.innerHTML = '<p class="texto-ayuda">Todavía no hay presentes registrados hoy.</p>';
                return;
            }
            contenedor.innerHTML = `
                <div class="tarjeta-curso ${!cursoFiltroActual ? 'tarjeta-activa' : ''}" onclick="filtrarPorCurso(null)">
                    <div class="tarjeta-curso-nombre">Todos</div>
                    <div class="tarjeta-curso-cantidad">${data.cursos.reduce((s, c) => s + c.presentes, 0)}</div>
                </div>
            ` + data.cursos.map(c => `
                <div class="tarjeta-curso ${cursoFiltroActual === c.curso ? 'tarjeta-activa' : ''}" onclick="filtrarPorCurso('${c.curso}')">
                    <div class="tarjeta-curso-nombre">${c.curso}</div>
                    <div class="tarjeta-curso-cantidad">${c.presentes}</div>
                    <button class="tarjeta-curso-descargar" onclick="event.stopPropagation(); descargarCSV('${c.curso}')">📥 Descargar</button>
                </div>
            `).join('');
        })
        .catch(err => console.error('Error al cargar resumen:', err));
}

function filtrarPorCurso(curso) {
    cursoFiltroActual = curso;
    document.getElementById('tituloTabla').innerText = curso ? `Curso ${curso}` : 'Todos los cursos';
    cargarResumen();
    cargarRegistros();
}

function cargarRegistros() {
    const url = cursoFiltroActual
        ? `/admin/api/registros?curso=${encodeURIComponent(cursoFiltroActual)}`
        : '/admin/api/registros';

    fetch(url)
        .then(res => res.json())
        .then(data => {
            registrosGlobales = data.registros || []; // Guardamos en la variable global
            renderizarTablaRegistros(); // Renderizamos aplicando los filtros
        })
        .catch(err => console.error('Error al cargar registros:', err));
}

// NUEVO: Función encargada de filtrar y dibujar la tabla dinámicamente
function renderizarTablaRegistros() {
    const tabla = document.getElementById('tablaRegistros');
    if (!tabla) return;

    // Aplicamos el filtro de turno/contraturno sobre los registros globales
    const filtrados = registrosGlobales.filter(r => {
        const turnoStr = (r.Turno || "").toLowerCase();
        
        if (filtroTurnoActual === 'habitual') {
            // Consideramos habitual si no contiene palabras de contraturno o materia especial
            return !turnoStr.includes('contraturno') && !turnoStr.includes('materia') && turnoStr !== 'especial';
        } else if (filtroTurnoActual === 'contraturno') {
            // Consideramos contraturno si especifica una materia o contraturno
            return turnoStr.includes('contraturno') || turnoStr.includes('materia') || (turnoStr !== '' && turnoStr !== 'habitual' && turnoStr !== 'entrada');
        }
        return true; // 'todos'
    });

    if (filtrados.length === 0) {
        tabla.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #6b7280;"><em>No hay registros para mostrar con este filtro.</em></td></tr>';
        return;
    }

    tabla.innerHTML = filtrados.map(r => `
        <tr>
            <td>${r.Hora}</td>
            <td>${r.Alumno}</td>
            <td>${r.Curso}</td>
            <td><span style="background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 12px;">${r.Turno || 'Habitual'}</span></td>
            <td>${r.Estado === 'TARDE' ? '<span class="pill pill-tarde">⏰ Tarde</span>' : '<span class="pill pill-presente">✅ A tiempo</span>'}</td>
        </tr>
    `).join('');
}

// NUEVO: Función que cambia el filtro al hacer clic en los botones de solapas
function filtrarPorTurno(tipo, botonElement) {
    filtroTurnoActual = tipo;

    // Cambiar clases visuales de los botones de filtro
    document.querySelectorAll('.btn-filtro-turno').forEach(b => b.classList.remove('activo'));
    if (botonElement) {
        botonElement.classList.add('activo');
    }

    renderizarTablaRegistros();
}

function descargarCSV(curso) {
    window.location.href = `/admin/descargar_asistencia/${encodeURIComponent(curso)}`;
}

function reentrenar() {
    statusAdmin.innerText = '🔄 Actualizando...';
    fetch('/admin/reentrenar_rostros', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    })
    .then(res => res.json())
    .then(data => { statusAdmin.innerText = `✅ Listo: ${data.alumnos_cargados} alumnos cargados`; })
    .catch(err => {
        console.error('Error al reentrenar:', err);
        statusAdmin.innerText = '❌ Error de conexión';
    });
}

// ------------------------------------------------------------------
// TAB Horarios
// ------------------------------------------------------------------
function aplicarHorarioMasivo() {
    const cursosSeleccionados = Array.from(document.querySelectorAll('#checkboxCursos input:checked')).map(el => el.value);
    if (cursosSeleccionados.length === 0) { alert('Marcá al menos un curso.'); return; }

    const hora_entrada = document.getElementById('masivoHora').value;
    const tolerancia_minutos = document.getElementById('masivoTolerancia').value;

    fetch('/admin/api/horarios/turno_habitual_multiple', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cursos: cursosSeleccionados, hora_entrada, tolerancia_minutos })
    })
    .then(res => res.json())
    .then(data => {
        statusAdmin.innerText = data.ok
            ? `✅ Horario aplicado a ${data.cursos_actualizados} curso(s)`
            : `❌ ${data.mensaje}`;
        if (data.ok) cargarHorarios();
    })
    .catch(err => {
        console.error('Error al aplicar horario masivo:', err);
        statusAdmin.innerText = '❌ Error de conexión';
    });
}

function cargarHorarios() {
    fetch('/admin/api/horarios')
        .then(res => res.json())
        .then(data => {
            renderizarAcordeonCursos(data.cursos || {});
            renderizarGruposTransversales(data.grupos_transversales || {});
        })
        .catch(err => console.error('Error al cargar horarios:', err));
}

function badgesDias(diasSeleccionados) {
    return DIAS.map(d => `
        <span class="dia-badge ${diasSeleccionados.includes(d.clave) ? 'dia-activo' : ''}">${d.letra}</span>
    `).join('');
}

function checkboxesDias(prefijoId, diasSeleccionados) {
    return DIAS.map(d => `
        <label class="dia-checkbox">
            <input type="checkbox" id="${prefijoId}-${d.clave}" ${diasSeleccionados.includes(d.clave) ? 'checked' : ''}>
            ${d.letra}
        </label>
    `).join('');
}

function leerDiasSeleccionados(prefijoId) {
    return DIAS.filter(d => document.getElementById(`${prefijoId}-${d.clave}`).checked).map(d => d.clave);
}

function renderizarAcordeonCursos(cursos) {
    const contenedor = document.getElementById('acordeonCursos');
    const nombresCursos = Object.keys(cursos).sort();

    if (nombresCursos.length === 0) {
        contenedor.innerHTML = '<p class="texto-ayuda">No hay cursos en la carpeta rostros/.</p>';
        return;
    }

    contenedor.innerHTML = nombresCursos.map(curso => {
        const cfg = cursos[curso];
        const contraturnos = cfg.contraturnos || [];

        return `
        <div class="acordeon-item">
            <div class="acordeon-cabecera" onclick="toggleAcordeon('${curso}')">
                <span><strong>${curso}</strong> — entra a las ${cfg.turno_habitual.hora_entrada}</span>
                <span id="flecha-${curso}">▼</span>
            </div>
            <div class="acordeon-cuerpo" id="cuerpo-${curso}" style="display:none;">

                <h4>Horario habitual</h4>
                <div class="fila-horario">
                    <label>Hora de entrada <input type="time" id="th-hora-${curso}" value="${cfg.turno_habitual.hora_entrada}"></label>
                    <label>Tolerancia (min) <input type="number" id="th-tol-${curso}" value="${cfg.turno_habitual.tolerancia_minutos}" min="0" max="120"></label>
                    <button onclick="guardarTurnoHabitual('${curso}')">Guardar</button>
                </div>

                <h4>Materias con horario especial</h4>
                <div id="contraturnos-${curso}">
                    ${contraturnos.length === 0 ? '<p class="texto-ayuda">Este curso no tiene materias con horario especial.</p>' : ''}
                    ${contraturnos.map(c => `
                        <div class="tarjeta-contraturno">
                            <div><strong>${c.materia}</strong></div>
                            <div>${badgesDias(c.dias)}</div>
                            <div>${c.hora_inicio} a ${c.hora_fin} (tolerancia ${c.tolerancia_minutos} min)</div>
                            <button class="btn-danger" onclick="eliminarContraturno('${curso}', '${c.id}')">Eliminar</button>
                        </div>
                    `).join('')}
                </div>

                <h4>Agregar materia con horario especial</h4>
                <div class="fila-horario">
                    <label>Materia <input type="text" id="nuevo-materia-${curso}" placeholder="Ej: Ed. Física"></label>
                </div>
                <div class="dias-checkbox-fila">${checkboxesDias(`nuevo-dia-${curso}`, [])}</div>
                <div class="fila-horario">
                    <label>Desde <input type="time" id="nuevo-inicio-${curso}" value="08:00"></label>
                    <label>Hasta <input type="time" id="nuevo-fin-${curso}" value="09:00"></label>
                    <label>Tolerancia (min) <input type="number" id="nuevo-tol-${curso}" value="10" min="0" max="120"></label>
                    <button onclick="agregarContraturno('${curso}')">Agregar</button>
                </div>
            </div>
        </div>
        `;
    }).join('');
}

function toggleAcordeon(curso) {
    const cuerpo = document.getElementById(`cuerpo-${curso}`);
    const flecha = document.getElementById(`flecha-${curso}`);
    const abierto = cuerpo.style.display !== 'none';
    cuerpo.style.display = abierto ? 'none' : 'block';
    flecha.innerText = abierto ? '▼' : '▲';
}

function guardarTurnoHabitual(curso) {
    const hora_entrada = document.getElementById(`th-hora-${curso}`).value;
    const tolerancia_minutos = document.getElementById(`th-tol-${curso}`).value;

    fetch('/admin/api/horarios/turno_habitual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ curso, hora_entrada, tolerancia_minutos })
    })
    .then(res => res.json())
    .then(data => {
        statusAdmin.innerText = data.ok ? `✅ Horario habitual de ${curso} actualizado` : `❌ ${data.mensaje}`;
        if (data.ok) cargarHorarios();
    })
    .catch(err => {
        console.error('Error al guardar turno habitual:', err);
        statusAdmin.innerText = '❌ Error de conexión';
    });
}

function agregarContraturno(curso) {
    const materia = document.getElementById(`nuevo-materia-${curso}`).value.trim();
    const dias = leerDiasSeleccionados(`nuevo-dia-${curso}`);
    const hora_inicio = document.getElementById(`nuevo-inicio-${curso}`).value;
    const hora_fin = document.getElementById(`nuevo-fin-${curso}`).value;
    const tolerancia_minutos = document.getElementById(`nuevo-tol-${curso}`).value;

    if (!materia) { alert('Escribí el nombre de la materia.'); return; }
    if (dias.length === 0) { alert('Marcá al menos un día.'); return; }

    fetch('/admin/api/horarios/contraturno', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ curso, materia, dias, hora_inicio, hora_fin, tolerancia_minutos })
    })
    .then(res => res.json())
    .then(data => {
        statusAdmin.innerText = data.ok ? `✅ Materia agregada a ${curso}` : `❌ ${data.mensaje}`;
        if (data.ok) cargarHorarios();
    })
    .catch(err => {
        console.error('Error al agregar contraturno:', err);
        statusAdmin.innerText = '❌ Error de conexión';
    });
}

function eliminarContraturno(curso, id) {
    if (!confirm('¿Eliminar esta materia con horario especial?')) return;

    fetch('/admin/api/horarios/contraturno/eliminar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ curso, id })
    })
    .then(res => res.json())
    .then(data => {
        statusAdmin.innerText = data.ok ? '✅ Eliminado' : `❌ ${data.mensaje}`;
        if (data.ok) cargarHorarios();
    })
    .catch(err => {
        console.error('Error al eliminar contraturno:', err);
        statusAdmin.innerText = '❌ Error de conexión';
    });
}

// ------------------------------------------------------------------
// Grupos transversales (Inglés) — informativo
// ------------------------------------------------------------------
function renderizarGruposTransversales(grupos) {
    const contenedor = document.getElementById('listaIngles');
    const nombres = Object.keys(grupos).sort();

    if (nombres.length === 0) {
        contenedor.innerHTML = '<p class="texto-ayuda">No hay niveles cargados todavía.</p>';
        return;
    }

    contenedor.innerHTML = nombres.map(nombre => {
        const g = grupos[nombre];
        return `
            <div class="tarjeta-contraturno">
                <div><strong>${nombre}</strong></div>
                <div>${badgesDias(g.dias)}</div>
                <div>${g.hora_inicio} a ${g.hora_fin}</div>
            </div>
        `;
    }).join('');
}