// static/app.js
// ----------------
// Cámara + confirmación manual, y enrolamiento/identificación de
// huella por ID numérico (sensor Suprema).

const video = document.getElementById('webcam');
const statusBox = document.getElementById('status');
const diagBox = document.getElementById('diagnostico');
const cursoSelect = document.getElementById('cursoSelect');
const btnEnrolar = document.getElementById('btnEnrolar');
const statusHuella = document.getElementById('statusHuella');

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
            verificarSensorHuella();
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
                mostrarConfirmacion(data.alumno, data.curso, 'FACIAL');
            } else if (!data.detectado && !esperandoConfirmacion) {
                setStatus("🔍 Buscando alumnos...", null);
            }
        })
        .catch(err => console.error('Error en /procesar_fotograma:', err));
    }, 1000);
}

// ------------------------------------------------------------------
// Confirmación manual
// ------------------------------------------------------------------
function mostrarConfirmacion(alumno, curso, metodo) {
    esperandoConfirmacion = true;
    candidatoActual = { alumno, curso, metodo };

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
            setStatus(`✅ PRESENTE: ${candidatoActual.alumno} (${candidatoActual.curso})`, 'ok');
            actualizarTabla(candidatoActual.alumno, candidatoActual.metodo);
        } else {
            setStatus(`ℹ️ ${candidatoActual.alumno} ya estaba presente hoy`, 'ok');
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

// ------------------------------------------------------------------
// Biometría dactilar (por ahora solo confirma que el sensor identificó
// un ID — falta unirlo con el nombre del alumno cuando tengamos la
// tabla ALUMNOS)
// ------------------------------------------------------------------
function verificarSensorHuella() {
    fetch('/estado_hardware')
        .then(res => res.json())
        .then(data => {
            statusHuella.innerText = data.sensor_huella_disponible
                ? "🟢 Sensor de huella conectado"
                : "⚪ Sensor de huella no conectado (solo cámara por ahora)";
        })
        .catch(() => { statusHuella.innerText = "⚪ No se pudo consultar el estado del sensor"; });
}

function enrolarHuella() {
    const idHuella = document.getElementById('idHuella').value;
    if (!idHuella) { alert("Ingresá un ID numérico primero."); return; }

    btnEnrolar.disabled = true;
    statusHuella.innerText = `☝️ Pedile al alumno que apoye el dedo dos veces en el lector...`;

    fetch('/enrolar_huella', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_huella: parseInt(idHuella, 10) })
    })
    .then(res => res.json())
    .then(data => {
        statusHuella.innerText = data.ok ? `✅ ${data.mensaje}` : `❌ ${data.mensaje}`;
    })
    .catch(err => {
        console.error('Error en /enrolar_huella:', err);
        statusHuella.innerText = "❌ Error de conexión con el backend";
    })
    .finally(() => { btnEnrolar.disabled = false; });
}

// ------------------------------------------------------------------
function actualizarTabla(nombre, metodo) {
    const tabla = document.getElementById('tablaAsistencia');
    const hora = new Date().toLocaleTimeString();
    if (tabla.firstChild && tabla.firstChild.innerText.includes(nombre)) return;

    tabla.insertAdjacentHTML('afterbegin', `<tr><td>${hora}</td><td>${nombre}</td><td>${metodo}</td></tr>`);

    setTimeout(() => {
        if (statusBox.innerText.includes(nombre)) setStatus("🔍 Buscando alumnos...", null);
    }, 3000);
}

function descargarCSV() {
    window.location.href = '/descargar_asistencia';
}