// static/app.js
// ----------------
// Versión mínima: cámara + selección de curso + confirmación manual.
// No hay persistencia todavía (ni CSV ni huella) — la confirmación
// solo se refleja en la tabla en memoria de esta sesión.

const video = document.getElementById('webcam');
const statusBox = document.getElementById('status');
const diagBox = document.getElementById('diagnostico');
const cursoSelect = document.getElementById('cursoSelect');

const confirmBox = document.getElementById('confirmacion');
const confirmNombre = document.getElementById('confirmNombre');
const confirmCurso = document.getElementById('confirmCurso');

let esperandoConfirmacion = false;
let candidatoActual = null;
let timeoutConfirmacion = null;

function setStatus(texto, tipo) {
    statusBox.innerText = texto;
    statusBox.classList.remove('error', 'ok');
    if (tipo) statusBox.classList.add(tipo);
}

function contextoEsSeguro() {
    return window.isSecureContext === true;
}

// ------------------------------------------------------------------
fetch('/obtener_cursos')
    .then(res => res.json())
    .then(data => {
        cursoSelect.innerHTML = "";
        if (!data.cursos || data.cursos.length === 0) {
            cursoSelect.innerHTML = "<option>No hay carpetas en 'rostros'</option>";
            setStatus("❌ No hay subcarpetas dentro del directorio 'rostros'.", 'error');
            return;
        }
        data.cursos.forEach(curso => {
            const option = document.createElement('option');
            option.value = curso;
            option.innerText = `Curso: ${curso}`;
            cursoSelect.appendChild(option);
        });
        setStatus("🔍 Buscando alumnos en cámara...", null);
        iniciarCamara();
    })
    .catch(err => {
        console.error('Error al pedir /obtener_cursos:', err);
        setStatus("❌ No se pudo conectar con el backend (¿está corriendo app.py?)", 'error');
    });

// ------------------------------------------------------------------
// Cámara
// ------------------------------------------------------------------
function iniciarCamara() {
    if (!contextoEsSeguro()) {
        setStatus("❌ El navegador bloquea la cámara: accedé por http://localhost:8000, no por una IP.", 'error');
        diagBox.innerText = `Origen actual: ${window.location.origin} (getUserMedia exige https:// o localhost)`;
        return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setStatus("❌ Este navegador no soporta acceso a cámara (getUserMedia no disponible).", 'error');
        return;
    }

    navigator.mediaDevices.enumerateDevices()
        .then(dispositivos => {
            const tieneCamara = dispositivos.some(d => d.kind === 'videoinput');
            if (!tieneCamara) {
                setStatus("❌ No se detectó ninguna cámara conectada al sistema.", 'error');
                return;
            }
            solicitarPermisoCamara();
        })
        .catch(() => solicitarPermisoCamara());
}

function solicitarPermisoCamara() {
    navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } })
        .then(stream => {
            video.srcObject = stream;
            diagBox.innerText = "";
            iniciarBucleAnalisis();
        })
        .catch(err => {
            console.error('Error de getUserMedia:', err.name, err.message);
            const mensajes = {
                NotAllowedError: "❌ Permiso de cámara denegado. Revisá el ícono de cámara/candado en la barra de direcciones.",
                NotFoundError: "❌ No se encontró ninguna cámara disponible.",
                NotReadableError: "❌ La cámara está siendo usada por otra aplicación.",
            };
            setStatus(mensajes[err.name] || `❌ Error de cámara: ${err.name}`, 'error');
            diagBox.innerText = err.message || '';
        });
}

function capturarFrame() {
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.90);
}

function iniciarBucleAnalisis() {
    setInterval(() => {
        if (esperandoConfirmacion) return;
        if (!video.srcObject || video.videoWidth === 0) return;

        fetch('/procesar_fotograma', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ imagen: capturarFrame(), curso: cursoSelect.value })
        })
        .then(res => res.json())
        .then(data => {
            if (data.detectado && !esperandoConfirmacion) {
                mostrarConfirmacion(data.alumno, data.curso);
            } else if (!data.detectado && !esperandoConfirmacion) {
                setStatus("🔍 Buscando alumnos...", null);
            }
        })
        .catch(err => console.error('Error en /procesar_fotograma:', err));
    }, 1000);
}

// ------------------------------------------------------------------
// Confirmación manual (sin persistencia todavía)
// ------------------------------------------------------------------
function mostrarConfirmacion(alumno, curso) {
    esperandoConfirmacion = true;
    candidatoActual = { alumno, curso };

    confirmNombre.innerText = alumno;
    confirmCurso.innerText = curso;
    confirmBox.style.display = 'block';
    setStatus(`👀 Candidato detectado: ${alumno}`, null);

    clearTimeout(timeoutConfirmacion);
    timeoutConfirmacion = setTimeout(() => {
        if (esperandoConfirmacion) rechazarAsistencia();
    }, 10000);
}

function confirmarAsistencia() {
    if (!candidatoActual) return;
    clearTimeout(timeoutConfirmacion);

    fetch('/confirmar_asistencia', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(candidatoActual)
    })
    .then(res => res.json())
    .then(data => {
        if (data.registrado) {
            const etiqueta = data.estado === 'TARDE' ? '⏰ TARDE' : '✅ PRESENTE';
            setStatus(`${etiqueta}: ${candidatoActual.alumno} (${candidatoActual.curso})`, 'ok');
        } else {
            setStatus(`ℹ️ ${candidatoActual.alumno} ya tenía registro hoy`, 'ok');
        }
    })
    .catch(err => {
        console.error('Error en /confirmar_asistencia:', err);
        setStatus("❌ Error al registrar la asistencia", 'error');
    })
    .finally(() => cerrarConfirmacion());
}

function rechazarAsistencia() {
    clearTimeout(timeoutConfirmacion);
    setStatus("🔍 Buscando alumnos...", null);
    cerrarConfirmacion();
}

function cerrarConfirmacion() {
    confirmBox.style.display = 'none';
    candidatoActual = null;
    setTimeout(() => { esperandoConfirmacion = false; }, 1500);
}