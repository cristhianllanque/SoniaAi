let phase = 'idle'; // idle | listening | thinking | speaking
let sequence = 0;
let requestController = null;
let recognition = null;
let micPressed = false;
let recording = false;
let recognitionTicket = 0;
let interestTimer = null;
let interestPending = false;
let detectionEnabled = false;
let inactivityTimer = null;
let audioTimer = null;
let currentProduct = null;
let currentTeaserProduct = null;
let whatsappNumber = '';
let currentMood = 'amable';

// Autonomous Conversation V1 State
let autoListening = false;
let autoListenTimer = null;
let speechWaitTimer = null;
let silenceTimer = null;
let postTtsSafetyTimer = null;
let accumulatedTranscript = '';
let isSpeakingDetected = false;
let reminderGivenInTurn = false;

let autonomyConfig = {
    enabled: true,
    presence_min_seconds: 5.0,
    face_facing_seconds: 2.0,
    post_tts_pause_ms: 500,
    silence_reminder_seconds: 12.0,
    session_inactivity_seconds: 90.0,
    farewell_cooldown_seconds: 30.0
};

let sessionContext = {
    session_id: null,
    current_code: null,
    last_color: null,
    last_talla: null,
    viewed_codes: [],
    last_intent: null,
    last_robot_question: null
};

function resetSessionContext() {
    sessionContext = {
        session_id: null,
        current_code: null,
        last_color: null,
        last_talla: null,
        viewed_codes: [],
        last_intent: null,
        last_robot_question: null
    };
    reminderGivenInTurn = false;
}

const el = id => document.getElementById(id);

function setMood(mood) {
    currentMood = mood || 'amable';
    const moodClasses = ['mood-amable', 'mood-alegre', 'mood-entusiasmada', 'mood-curiosa', 'mood-pensativa', 'mood-empatica', 'mood-despedida'];
    document.querySelectorAll('.hero-face, .mini-face').forEach(face => {
        moodClasses.forEach(c => face.classList.remove(c));
        if (currentMood && currentMood !== 'amable') {
            face.classList.add('mood-' + currentMood);
        }
    });
}

function setProductMicState(state) {
    const btn = el('productMicBtn');
    const label = el('productMicLabel');
    const bubble = el('conversationBubble');
    const orb = el('speechStatusOrb');
    const orbText = el('orbText');
    if (bubble) {
        bubble.classList.remove('speaking', 'listening', 'thinking');
        if (state !== 'idle') bubble.classList.add(state);
    }
    if (orb) {
        orb.classList.remove('speaking', 'listening', 'thinking');
        if (state !== 'idle') orb.classList.add(state);
    }
    if (btn) {
        btn.classList.remove('active-listening', 'thinking', 'speaking');
    }
    if (state === 'listening') {
        if (btn) btn.classList.add('active-listening');
        if (label) label.textContent = '🟡 Te estoy escuchando... ¡Habla ahora!';
        if (el('bubbleStatus')) el('bubbleStatus').textContent = '🟡 Puedes hablar, te estoy escuchando...';
        if (orbText) orbText.textContent = 'Escuchando';
    } else if (state === 'thinking') {
        if (btn) btn.classList.add('thinking');
        if (label) label.textContent = '🟣 Consultando con el robot...';
        if (el('bubbleStatus')) el('bubbleStatus').textContent = '🟣 Pensando en tu consulta...';
        if (orbText) orbText.textContent = 'Pensando';
    } else if (state === 'speaking') {
        if (btn) btn.classList.add('speaking');
        if (label) label.textContent = '🟢 El robot te está respondiendo...';
        if (el('bubbleStatus')) el('bubbleStatus').textContent = '🟢 Respondiendo...';
        if (orbText) orbText.textContent = 'Hablando';
    } else {
        if (label) label.textContent = '🎤 Puedes hablar o presionar para consultar';
        if (el('bubbleStatus')) el('bubbleStatus').textContent = 'Haz una consulta o di "chau"...';
        if (orbText) orbText.textContent = 'En espera';
    }
}

function updateConversationBubble(robotText, userQuery = '', statusText = '') {
    const bubbleText = el('bubbleText');
    if (bubbleText && robotText) bubbleText.textContent = robotText;
    const userPreview = el('userQueryPreview');
    const userText = el('userQueryText');
    if (userPreview && userText) {
        if (userQuery) {
            userText.textContent = userQuery;
            userPreview.classList.remove('hidden');
        } else {
            userPreview.classList.add('hidden');
        }
    }
    const bubbleStatus = el('bubbleStatus');
    if (bubbleStatus && statusText) {
        bubbleStatus.textContent = statusText;
    }
}

function setPhase(value) {
    phase = value;
    document.querySelectorAll('.hero-face, .mini-face').forEach(face => {
        face.classList.remove('speaking', 'thinking', 'listening');
        if (value !== 'idle') face.classList.add(value);
    });
    if (value === 'thinking') setMood('pensativa');
    if (value === 'listening') setMood('curiosa');
    el('searchBtn')?.setAttribute('aria-busy', value === 'thinking' ? 'true' : 'false');
    
    // Update Hero Mic Button
    const mic = el('micBtn');
    if (mic) {
        mic.classList.toggle('active-listening', value === 'listening');
        mic.classList.toggle('recording', value === 'listening');
    }

    // Update Hero Speech Status Orb
    const heroOrb = el('heroSpeechStatusOrb');
    const heroOrbText = el('heroOrbText');
    if (heroOrb) {
        heroOrb.classList.remove('speaking', 'listening', 'thinking');
        if (value !== 'idle') heroOrb.classList.add(value);
    }
    if (heroOrbText) {
        if (value === 'listening') heroOrbText.textContent = 'Escuchando';
        else if (value === 'thinking') heroOrbText.textContent = 'Pensando';
        else if (value === 'speaking') heroOrbText.textContent = 'Hablando';
        else heroOrbText.textContent = 'En espera';
    }

    // Update interaction hint on hero screen
    const hint = el('interactionHint');
    if (hint && !currentProduct) {
        if (value === 'listening') {
            hint.textContent = '🟡 Te estoy escuchando... ¡Dime qué pollera buscas!';
            hint.classList.add('live');
        } else if (value === 'thinking') {
            hint.textContent = '🟣 Consultando en el catálogo...';
            hint.classList.remove('live');
        } else if (value === 'speaking') {
            hint.textContent = '🟢 Respondiendo...';
            hint.classList.remove('live');
        } else {
            hint.textContent = 'Mantén presionado el micrófono para hablar o acércate...';
            hint.classList.remove('live');
        }
    }

    setProductMicState(value);
}

function showError(message = '') {
    el('errorPanel').textContent = message;
    el('errorPanel').classList.toggle('hidden', !message);
}

function showText(text = '') {
    const textEl = el('assistantText');
    if (textEl) textEl.textContent = text;
    if (text && el('bubbleText')) {
        el('bubbleText').textContent = text;
    }
}

function unlockDetection() {
    if (detectionEnabled) api.request('/api/audio/unlock', {method: 'POST', timeout: 5000}).catch(() => {});
}

function stopAudio() {
    clearTimeout(audioTimer);
    audioTimer = null;
    const audio = el('robotAudio');
    audio.onended = audio.onerror = audio.onpause = null;
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
}

const thinkingClips = [
    '/static/audio/thinking_1.mp3',
    '/static/audio/thinking_2.mp3',
    '/static/audio/thinking_3.mp3',
    '/static/audio/thinking_4.mp3'
];
let thinkingActive = false;
let thinkingWaitPromise = null;

function playThinkingAudio(ticket) {
    if (ticket !== sequence || typeof HTMLAudioElement === 'undefined') return;
    const clip = thinkingClips[Math.floor(Math.random() * thinkingClips.length)];
    const audio = el('robotAudio');
    if (!audio) return;
    thinkingActive = true;
    audio.src = clip;
    audio.play().catch(() => { thinkingActive = false; });
    thinkingWaitPromise = new Promise(resolve => {
        const done = () => {
            audio.removeEventListener('ended', done);
            audio.removeEventListener('error', done);
            thinkingActive = false;
            resolve();
        };
        audio.addEventListener('ended', done, {once: true});
        audio.addEventListener('error', done, {once: true});
        setTimeout(done, 2500);
    });
}

function cancelActive() {
    sequence += 1;
    stopAutoListen();
    clearTimeout(postTtsSafetyTimer);
    postTtsSafetyTimer = null;
    thinkingActive = false;
    thinkingWaitPromise = null;
    requestController?.abort();
    requestController = null;
    if (recognition && (phase === 'listening' || recording)) {
        try { recognition.abort(); } catch (_) {}
    }
    stopAudio();
    setPhase('idle');
    unlockDetection();
    return sequence;
}

function beginRequest() {
    const ticket = cancelActive();
    requestController = new AbortController();
    setPhase('thinking');
    showError();
    return {ticket, signal: requestController.signal};
}

async function playAudioFromUrl(url, ticket = sequence, onEnded = null) {
    if (ticket !== sequence) return;
    // Acoustic protection: Ensure recognition is stopped while audio plays
    if (recognition && recording) {
        try { recognition.abort(); } catch (_) {}
    }
    if (!url) {
        setPhase('idle');
        unlockDetection();
        if (typeof onEnded === 'function') onEnded();
        return;
    }
    const audio = el('robotAudio');
    let settled = false;
    const finish = () => {
        if (settled || ticket !== sequence) return;
        settled = true;
        stopAudio();
        setPhase('idle');
        unlockDetection();
        if (typeof onEnded === 'function') onEnded();
    };
    audio.onended = finish;
    audio.onerror = () => {
        if (ticket !== sequence) return;
        showError('No se pudo reproducir la voz. Intenta nuevamente.');
        finish();
    };
    audio.onpause = finish;
    audio.src = url;
    setPhase('speaking');
    audioTimer = setTimeout(finish, 90000);
    try {
        await audio.play();
    } catch (_) {
        if (ticket === sequence) {
            showError('La voz no está disponible en este momento. Intenta nuevamente.');
            finish();
        }
    }
}

async function applySpeech(data, ticket) {
    if (ticket !== sequence) return;
    if (thinkingActive && thinkingWaitPromise) {
        await Promise.race([thinkingWaitPromise, new Promise(r => setTimeout(r, 2000))]);
        thinkingActive = false;
        thinkingWaitPromise = null;
    }
    if (ticket !== sequence) return;
    showText(data.text || '');
    if (data.mood) setMood(data.mood);
    if (data.context) {
        sessionContext = Object.assign(sessionContext, data.context);
    }
    if (data.pollera && data.action === 'show_pollera') {
        mostrarResultado(data.pollera);
        sessionContext.current_code = data.pollera.codigo;
        if (!sessionContext.viewed_codes.includes(data.pollera.codigo)) {
            sessionContext.viewed_codes.push(data.pollera.codigo);
        }
    }
    if (data.action === 'greeting' && !data.imagen_url) {
        el('robotWrapper').classList.remove('presenting');
    } else if (data.imagen_url && !currentProduct) {
        api.setImage(el('teaserImage'), data.imagen_url);
        el('robotWrapper').classList.add('presenting');
        if (data.pollera_teaser) {
            currentTeaserProduct = data.pollera_teaser;
        }
    } else if (!data.imagen_url && !currentProduct && data.action !== 'offer') {
        el('robotWrapper').classList.remove('presenting');
    }
    resetInactivityTimer();
    await playAudioFromUrl(data.audio_url, ticket, () => {
        if (ticket !== sequence) return;
        if (data.action === 'farewell') {
            // Activate cooldown so robot doesn't immediately re-greet someone leaving
            const cooldownSec = autonomyConfig.farewell_cooldown_seconds || 30;
            api.request('/api/vision/cooldown?seconds=' + encodeURIComponent(cooldownSec), {method: 'POST'}).catch(() => {});
            resetSessionContext();
            volverInicio();
        } else {
            // Echo shield: Acoustic pause post-TTS before resuming microphone
            const pauseMs = autonomyConfig.post_tts_pause_ms || 500;
            clearTimeout(postTtsSafetyTimer);
            postTtsSafetyTimer = setTimeout(() => {
                if (ticket === sequence && phase === 'idle' && autonomyConfig.enabled) {
                    startAutoListen();
                }
            }, pauseMs);
        }
    });
}

function requestError(error, ticket) {
    if (ticket !== sequence) return;
    setPhase('idle');
    unlockDetection();
    showError(error.name === 'AbortError'
        ? 'La respuesta tardó demasiado. Intenta nuevamente.'
        : error.message || 'No se pudo conectar. Intenta nuevamente.');
}

async function enviarMensajeVoz(message) {
    if (!message.trim()) return;
    reminderGivenInTurn = false;
    const {ticket, signal} = beginRequest();
    playThinkingAudio(ticket);
    try {
        const data = await api.request('/api/chat', {
            method: 'POST', signal,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message,
                codigo_actual: currentProduct?.codigo || sessionContext.current_code || null,
                context: sessionContext
            })
        });
        await applySpeech(data, ticket);
    } catch (error) {
        requestError(error, ticket);
    }
}

async function buscarPollera() {
    const message = el('codigoInput').value.trim();
    if (!message) return;
    resetInactivityTimer();
    if (!/^[a-z0-9_-]{1,50}$/i.test(message)) {
        await enviarMensajeVoz(message);
        return;
    }
    const {ticket, signal} = beginRequest();
    playThinkingAudio(ticket);
    try {
        let product;
        try {
            product = await api.request('/api/polleras/' + encodeURIComponent(message), {signal});
        } catch (error) {
            if (error.status !== 404) throw error;
            const data = await api.request('/api/chat', {
                method: 'POST', signal,
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message, codigo_actual: currentProduct?.codigo || null})
            });
            await applySpeech(data, ticket);
            return;
        }
        if (ticket !== sequence) return;
        mostrarResultado(product);
        const data = await api.request('/api/audio/detalles/' + encodeURIComponent(product.codigo), {signal});
        await applySpeech(data, ticket);
    } catch (error) {
        requestError(error, ticket);
    }
}

let currentProductImages = [];
let currentImageIndex = 0;
let galleryAutoTimer = null;

function stopGalleryAutoPlay() {
    if (galleryAutoTimer) {
        clearInterval(galleryAutoTimer);
        galleryAutoTimer = null;
    }
}

function startGalleryAutoPlay() {
    stopGalleryAutoPlay();
    if (currentProductImages.length <= 1) return;
    galleryAutoTimer = setInterval(() => {
        changeGalleryImageSmoothly(currentImageIndex + 1);
    }, 4000);
}

function changeGalleryImageSmoothly(nextIndex) {
    if (!currentProductImages.length) return;
    const imgEl = el('resImagen');
    if (!imgEl || currentProductImages.length <= 1) {
        updateGalleryView(nextIndex);
        return;
    }
    imgEl.classList.add('gallery-crossfade');
    setTimeout(() => {
        updateGalleryView(nextIndex);
        imgEl.classList.remove('gallery-crossfade');
    }, 250);
}

function updateGalleryView(index) {
    if (!currentProductImages.length) return;
    currentImageIndex = (index + currentProductImages.length) % currentProductImages.length;
    api.setImage(el('resImagen'), currentProductImages[currentImageIndex]);
    const dots = document.querySelectorAll('.gallery-dot');
    dots.forEach((d, i) => d.classList.toggle('active', i === currentImageIndex));
}

function setupGallery(images) {
    stopGalleryAutoPlay();
    currentProductImages = (images || []).filter(Boolean);
    currentImageIndex = 0;
    const prevBtn = el('galleryPrev');
    const nextBtn = el('galleryNext');
    const dotsContainer = el('galleryDots');
    
    // En modo público autónomo, ocultar flechas y puntos para no saturar la pantalla de 7"
    if (prevBtn) prevBtn.classList.add('hidden');
    if (nextBtn) nextBtn.classList.add('hidden');
    if (dotsContainer) {
        dotsContainer.classList.add('hidden');
        dotsContainer.replaceChildren();
        if (currentProductImages.length > 1) {
            currentProductImages.forEach((_, idx) => {
                const dot = document.createElement('span');
                dot.className = 'gallery-dot' + (idx === 0 ? ' active' : '');
                dot.addEventListener('click', () => {
                    updateGalleryView(idx);
                    startGalleryAutoPlay();
                });
                dotsContainer.append(dot);
            });
        }
    }
    if (currentProductImages.length > 1) {
        startGalleryAutoPlay();
    }
}

function mostrarResultado(data) {
    currentProduct = data;
    el('robotWrapper').classList.remove('presenting');
    el('robotWrapper').classList.add('hidden');
    if (el('heroView')) el('heroView').classList.add('hidden');
    el('productView').classList.remove('hidden');
    el('resCodigo').textContent = 'Código: ' + data.codigo;
    el('resNombre').textContent = data.nombre;
    el('resTalla').textContent = 'Talla: ' + data.talla;
    el('resDesc').textContent = data.descripcion;
    const estadoBadge = el('resEstado');
    if (estadoBadge) {
        const isAlquilada = (data.estado || '').toUpperCase() === 'ALQUILADA';
        estadoBadge.textContent = isAlquilada ? 'ALQUILADA' : 'DISPONIBLE';
        estadoBadge.className = 'badge ' + (isAlquilada ? 'badge-alquilada' : 'badge-disponible');
    }
    const images = data.imagenes || [data.imagen_url, data.imagen_url_2, data.imagen_url_3].filter(Boolean);
    setupGallery(images);
    api.setImage(el('resImagen'), images[0] || data.imagen_url);
    const finalPrice = Number(data.precio_final);
    const basePrice = Number(data.precio_base);
    const discounted = finalPrice < basePrice;
    el('resPrecioFinal').textContent = finalPrice.toFixed(2);
    el('resPrecioOriginal').textContent = basePrice.toFixed(2);
    el('resPrecioOriginalBox').classList.toggle('hidden', !discounted);
    el('resDiscountBadge').classList.toggle('hidden', !discounted);
    el('resDiscountBadge').textContent = '-' + Math.round((basePrice - finalPrice) / basePrice * 100) + '%';
    el('resSombrero').classList.toggle('active', data.incluye_sombrero);
    el('resManta').classList.toggle('active', data.incluye_manta);
    updateConversationBubble(
        '¡Aquí tienes ' + data.nombre + '! Puedes preguntarme por voz sobre precios, tallas, accesorios o pedir un descuento.',
        '',
        'Te escucho...'
    );
    updateContact();
    resetInactivityTimer();
}

function updateContact() {
    const button = el('whatsappBtn');
    button.disabled = !whatsappNumber;
    if (!currentProduct || !whatsappNumber) return;
    const message = 'Hola, me interesa consultar disponibilidad y condiciones de alquiler de ' +
        currentProduct.nombre + ' (Código: ' + currentProduct.codigo + ').';
    const url = 'https://wa.me/' + whatsappNumber + '?text=' + encodeURIComponent(message);
    button.onclick = () => window.open(url, '_blank', 'noopener,noreferrer');
    el('resQRCode').src = 'https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=' + encodeURIComponent(url);
    el('resQRCode').onerror = () => {
        el('resQRCode').alt = 'QR no disponible. Usa el botón de WhatsApp.';
    };
}

function volverInicio() {
    stopGalleryAutoPlay();
    currentProductImages = [];
    stopAutoListen();
    cancelActive();
    clearTimeout(inactivityTimer);
    inactivityTimer = null;
    currentProduct = null;
    currentTeaserProduct = null;
    resetSessionContext();
    el('robotWrapper').classList.remove('presenting');
    setMood('amable');
    const hint = el('interactionHint');
    if (hint) {
        hint.classList.remove('live');
        hint.textContent = 'Mantén presionado el micrófono para hablar o acércate...';
    }
    updateConversationBubble(
        '¿Tienes alguna consulta sobre esta pollera? Pregúntame sobre precios, tallas, descuentos o colores.',
        '',
        'Te escucho...'
    );
    el('productView').classList.add('hidden');
    el('robotWrapper').classList.remove('hidden');
    if (el('heroView')) el('heroView').classList.remove('hidden');
    el('codigoInput').value = '';
    el('codigoInput').focus();
    showText();
    showError();
}

function stopAutoListen() {
    autoListening = false;
    clearTimeout(autoListenTimer);
    autoListenTimer = null;
    clearTimeout(speechWaitTimer);
    speechWaitTimer = null;
    clearTimeout(silenceTimer);
    silenceTimer = null;
    clearTimeout(postTtsSafetyTimer);
    postTtsSafetyTimer = null;
    accumulatedTranscript = '';
    isSpeakingDetected = false;
    if (recognition && recording && !micPressed) {
        try { recognition.stop(); } catch (_) {}
    }
    const hint = el('interactionHint');
    if (hint && !currentProduct) {
        hint.classList.remove('live');
        hint.textContent = 'Mantén presionado el micrófono para hablar o acércate...';
    }
}

function startAutoListen() {
    if (!recognition || phase === 'speaking' || phase === 'thinking' || !autonomyConfig.enabled) return;
    stopAutoListen();
    autoListening = true;
    recognitionTicket = sequence;
    accumulatedTranscript = '';
    isSpeakingDetected = false;

    // The yellow indicator ONLY turns yellow inside recognition.onstart
    // once the microphone is verified to be actively running.

    const silenceMs = (autonomyConfig.silence_reminder_seconds || 12) * 1000;
    speechWaitTimer = setTimeout(async () => {
        if (autoListening && !isSpeakingDetected && phase === 'listening') {
            if (!reminderGivenInTurn) {
                reminderGivenInTurn = true;
                const {ticket, signal} = beginRequest();
                try {
                    const data = await api.request('/api/audio/recordatorio', {signal});
                    await applySpeech(data, ticket);
                } catch (_) {
                    stopAutoListen();
                    setPhase('idle');
                }
            } else {
                stopAutoListen();
                setPhase('idle');
            }
        }
    }, silenceMs);

    try {
        recognition.start();
    } catch (_) {}
}

function scheduleNextAutoListen(ms = 1500) {
    if (!autoListening || phase === 'speaking' || phase === 'thinking' || !autonomyConfig.enabled) return;
    clearTimeout(autoListenTimer);
    autoListenTimer = setTimeout(() => {
        if (autoListening && phase === 'idle') {
            startAutoListen();
        }
    }, ms);
}

async function enviarPreguntaConversacion(message) {
    if (!message || !message.trim() || !currentProduct) return;
    const query = message.trim();
    resetInactivityTimer();
    reminderGivenInTurn = false;
    stopAutoListen();
    updateConversationBubble('', query, '🟣 Pensando en tu consulta...');
    const {ticket, signal} = beginRequest();
    playThinkingAudio(ticket);
    try {
        const data = await api.request('/api/conversacion', {
            method: 'POST', signal,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message: query,
                codigo: currentProduct.codigo,
                context: sessionContext
            })
        });
        if (ticket === sequence && data.text) {
            updateConversationBubble(data.text, query, '🟢 Respondiendo...');
        }
        if (ticket === sequence && data.pollera && data.action === 'show_pollera') {
            mostrarResultado(data.pollera);
        }
        await applySpeech(data, ticket);
    } catch (error) {
        requestError(error, ticket);
        updateConversationBubble('Lo siento, no pude procesar la consulta. Intenta nuevamente.', query, 'Error');
    }
}

function resetInactivityTimer() {
    clearTimeout(inactivityTimer);
    const timeoutMs = (autonomyConfig.session_inactivity_seconds || 90) * 1000;
    if (currentProduct || autoListening) {
        inactivityTimer = setTimeout(volverInicio, timeoutMs);
    }
}

async function toggleDetection() {
    el('detectionBtn').disabled = true;
    try {
        const result = await api.request('/api/vision/' + (detectionEnabled ? 'stop' : 'start'), {method: 'POST'});
        detectionEnabled = ['starting', 'running'].includes(result.state);
        updateDetectionLabel(result);
    } catch (error) {
        showError(error.status === 401
            ? 'Activa la detección desde el equipo de la tienda o inicia sesión como administrador.'
            : error.message);
    } finally {
        el('detectionBtn').disabled = false;
    }
}

function updateDetectionLabel(result) {
    el('detectionBtn').textContent = detectionEnabled ? 'Detener detección' : 'Activar detección';
    el('detectionBtn').setAttribute('aria-pressed', String(detectionEnabled));
    el('detectionStatus').textContent = result.state === 'starting' ? 'Iniciando cámara…'
        : result.state === 'running' ? 'Detección activa' : 'Detección desactivada';
    if (result.error) showError(result.error);
}

async function pollInterest() {
    if (!detectionEnabled || interestPending || phase !== 'idle' || currentProduct || document.hidden) return;
    interestPending = true;
    const before = sequence;
    try {
        const result = await api.request('/api/check_interest', {timeout: 5000});
        detectionEnabled = ['starting', 'running'].includes(result.state);
        updateDetectionLabel(result);
        if (result.interested && before === sequence && phase === 'idle' && !currentProduct) {
            const {ticket, signal} = beginRequest();
            try {
                let data;
                try {
                    data = await api.request('/api/audio/ofertas', {signal});
                    if (!data || !data.text) throw new Error('empty offer');
                } catch (err) {
                    data = await api.request('/api/audio/saludo', {signal});
                }
                // Autonomous interest detection strictly keeps focus on robot face
                delete data.pollera;
                await applySpeech(data, ticket);
            } catch (error) {
                requestError(error, ticket);
            }
        }
    } catch (error) {
        if (error.status === 401 || error.status === 403) {
            detectionEnabled = false;
            updateDetectionLabel({state: 'stopped'});
        }
    } finally {
        interestPending = false;
    }
}

function startMic(event) {
    event?.preventDefault();
    if (!recognition || phase === 'listening') return;
    stopAutoListen();
    micPressed = true;
    cancelActive();
    recognitionTicket = sequence;
    setPhase('listening');
    resetInactivityTimer();
    showError();
    try {
        recognition.start();
    } catch (_) {
        setPhase('idle');
        showError('No se pudo activar el micrófono. Intenta nuevamente.');
    }
}

function stopMic(event) {
    event?.preventDefault();
    micPressed = false;
    if (recording) recognition?.stop();
}

document.addEventListener('DOMContentLoaded', () => {
    el('searchBtn').addEventListener('click', buscarPollera);
    el('backBtn').addEventListener('click', volverInicio);
    el('detectionBtn').addEventListener('click', toggleDetection);
    el('codigoInput').addEventListener('keydown', event => {
        if (event.key === 'Enter') buscarPollera();
    });
    el('stopAudioBtn').addEventListener('click', () => { cancelActive(); showText(); });
    document.addEventListener('pointerdown', resetInactivityTimer);
    document.addEventListener('keydown', resetInactivityTimer);
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.lang = 'es-PE';
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.onstart = () => {
            recording = true;
            // The circular yellow indicator turns yellow ONLY when recognition is genuinely started
            if (autoListening || micPressed) {
                setPhase('listening');
            } else {
                try { recognition.stop(); } catch (_) {}
            }
        };
        recognition.onend = () => {
            recording = false;
            if (recognitionTicket === sequence && phase === 'listening' && isSpeakingDetected && accumulatedTranscript.trim()) {
                const query = accumulatedTranscript.trim();
                stopAutoListen();
                if (currentProduct) {
                    enviarPreguntaConversacion(query);
                } else {
                    enviarMensajeVoz(query);
                }
                return;
            }
            if (autoListening && phase === 'listening') {
                try { recognition.start(); } catch (_) {
                    setPhase('idle');
                }
            } else if (phase === 'listening' && !micPressed) {
                setPhase('idle');
            }
        };
        recognition.onerror = event => {
            recording = false;
            if (event.error === 'no-speech') {
                return;
            }
            if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
                stopAutoListen();
                setPhase('idle');
                showError('El micrófono no tiene permisos activados. Usa el botón manual o escribe tu consulta.');
                return;
            }
            if (event.error !== 'aborted') {
                if (!autoListening) showError('No se pudo escuchar. Revisa el permiso del micrófono o escribe tu consulta.');
            }
            if (!autoListening && phase === 'listening') {
                setPhase('idle');
            }
        };
        recognition.onresult = event => {
            // ACOUSTIC ECHO PROTECTION:
            // Strictly ignore and discard any audio received while robot is speaking or thinking
            if (phase !== 'listening' || recognitionTicket !== sequence) return;

            let interim = '';
            let final = '';

            for (let i = 0; i < event.results.length; i++) {
                const item = event.results[i];
                if (item.isFinal) {
                    final += item[0].transcript + ' ';
                } else {
                    interim += item[0].transcript;
                }
            }

            const currentText = (final + interim).trim();
            if (!currentText) return;

            isSpeakingDetected = true;
            accumulatedTranscript = currentText;
            clearTimeout(speechWaitTimer);
            speechWaitTimer = null;

            if (currentProduct) {
                const preview = el('userQueryPreview');
                const userText = el('userQueryText');
                if (preview && userText) {
                    userText.textContent = currentText;
                    preview.classList.remove('hidden');
                }
                const bubbleStatus = el('bubbleStatus');
                if (bubbleStatus) {
                    bubbleStatus.textContent = '🟡 Escuchando: "' + currentText + '"...';
                }

                clearTimeout(silenceTimer);
                silenceTimer = setTimeout(() => {
                    if (recognitionTicket === sequence && phase === 'listening' && accumulatedTranscript.trim()) {
                        const query = accumulatedTranscript.trim();
                        stopAutoListen();
                        enviarPreguntaConversacion(query);
                    }
                }, 1300);
            } else {
                el('codigoInput').value = currentText;
                clearTimeout(silenceTimer);
                silenceTimer = setTimeout(() => {
                    if (recognitionTicket === sequence && phase === 'listening' && accumulatedTranscript.trim()) {
                        const query = accumulatedTranscript.trim();
                        stopAutoListen();
                        enviarMensajeVoz(query);
                    }
                }, 1300);
            }
        };
        el('micBtn').addEventListener('pointerdown', event => {
            el('micBtn').setPointerCapture(event.pointerId);
            startMic(event);
        });
        el('micBtn').addEventListener('pointerup', stopMic);
        el('micBtn').addEventListener('pointercancel', stopMic);
        el('micBtn').addEventListener('keydown', event => {
            if ([' ', 'Enter'].includes(event.key) && !event.repeat) startMic(event);
        });
        el('micBtn').addEventListener('keyup', event => {
            if ([' ', 'Enter'].includes(event.key)) stopMic(event);
        });

        // Product Mic Button (tap to toggle autonomous listening)
        const prodMic = el('productMicBtn');
        if (prodMic) {
            prodMic.addEventListener('click', event => {
                event.preventDefault();
                if (phase === 'listening') {
                    stopAutoListen();
                    setPhase('idle');
                } else if (phase === 'idle') {
                    startAutoListen();
                }
            });
        }
    } else {
        el('micBtn').hidden = true;
        el('interactionHint').textContent = 'Escribe un código o una consulta para comenzar.';
        if (el('productMicBtn')) el('productMicBtn').hidden = true;
    }

    // Quick suggestion chips in product view
    document.querySelectorAll('.chip-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const query = btn.getAttribute('data-query');
            if (query && currentProduct) {
                enviarPreguntaConversacion(query);
            }
        });
    });

    // Inline question text input in product view
    el('productSendBtn')?.addEventListener('click', () => {
        const input = el('productInput');
        if (input && input.value.trim() && currentProduct) {
            const query = input.value.trim();
            input.value = '';
            enviarPreguntaConversacion(query);
        }
    });
    el('productInput')?.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            const input = el('productInput');
            if (input && input.value.trim() && currentProduct) {
                const query = input.value.trim();
                input.value = '';
                enviarPreguntaConversacion(query);
            }
        }
    });

    const prev = el('galleryPrev');
    if (prev) prev.addEventListener('click', () => updateGalleryView(currentImageIndex - 1));
    const next = el('galleryNext');
    if (next) next.addEventListener('click', () => updateGalleryView(currentImageIndex + 1));
    const imgContainer = el('productImageContainer');
    if (imgContainer) {
        let touchStartX = 0;
        imgContainer.addEventListener('touchstart', e => {
            touchStartX = (e.changedTouches && e.changedTouches[0]) ? e.changedTouches[0].screenX : 0;
        }, {passive: true});
        imgContainer.addEventListener('touchend', e => {
            const touchEndX = (e.changedTouches && e.changedTouches[0]) ? e.changedTouches[0].screenX : 0;
            if (touchEndX - touchStartX > 40) {
                updateGalleryView(currentImageIndex - 1);
                startGalleryAutoPlay();
            } else if (touchStartX - touchEndX > 40) {
                updateGalleryView(currentImageIndex + 1);
                startGalleryAutoPlay();
            }
        }, {passive: true});
    }

    const toggleInputBtn = el('toggleInputBtn');
    if (toggleInputBtn) {
        toggleInputBtn.addEventListener('click', () => {
            const box = el('inlineQueryBox');
            if (box) {
                box.classList.toggle('hidden');
                if (!box.classList.contains('hidden')) {
                    el('productInput')?.focus();
                }
            }
        });
    }

    api.request('/api/config').then(data => {
        whatsappNumber = /^\d{8,15}$/.test(data.whatsapp_number) ? data.whatsapp_number : '';
        if (data.autonomy) {
            autonomyConfig = Object.assign(autonomyConfig, data.autonomy);
        }
        updateContact();
    }).catch(() => showError('No se pudo cargar el contacto de la tienda.'));
    const teaserBox = el('teaserContainer');
    if (teaserBox) {
        teaserBox.style.cursor = 'pointer';
        teaserBox.addEventListener('click', () => {
            if (currentTeaserProduct && !currentProduct) {
                mostrarResultado(currentTeaserProduct);
                const {ticket, signal} = beginRequest();
                api.request('/api/audio/detalles/' + encodeURIComponent(currentTeaserProduct.codigo), {signal})
                    .then(d => applySpeech(d, ticket))
                    .catch(err => requestError(err, ticket));
            }
        });
    }
    el('productView')?.addEventListener('pointerdown', resetInactivityTimer);
    interestTimer = setInterval(pollInterest, 2000);
    api.request('/api/vision/status', {timeout: 5000}).then(result => {
        detectionEnabled = ['starting', 'running'].includes(result.state);
        updateDetectionLabel(result);
    }).catch(() => {});
});

window.addEventListener('pagehide', () => {
    cancelActive();
    clearInterval(interestTimer);
    clearTimeout(inactivityTimer);
});
