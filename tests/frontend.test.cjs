const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = name => fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'js', name), 'utf8');

function harness(script = 'main.js') {
    const nodes = new Map();
    const calls = [];
    const timers = new Map();
    let timerId = 0;
    function node(id = '') {
        const classes = new Set();
        const attributes = new Map();
        return {
            id, children: [], textContent: '', value: '', disabled: false, paused: true,
            classList: {
                add(...names) { names.forEach(name => classes.add(name)); },
                remove(...names) { names.forEach(name => classes.delete(name)); },
                contains(name) { return classes.has(name); },
                toggle(name, on = !classes.has(name)) { if (on) classes.add(name); else classes.delete(name); }
            },
            set innerHTML(_) { throw new Error('Unsafe HTML insertion'); },
            setAttribute(name, value) { attributes.set(name, value); },
            getAttribute(name) { return attributes.get(name) ?? null; },
            removeAttribute(name) { attributes.delete(name); },
            append(...items) { this.children.push(...items); },
            replaceChildren(...items) { this.children = items; },
            addEventListener() {}, focus() {}, load() {},
            pause() { this.paused = true; this.onpause?.(); },
            play() { this.paused = false; return Promise.resolve(); },
            style: {}
        };
    }
    function element(id) {
        if (!nodes.has(id)) nodes.set(id, node(id));
        return nodes.get(id);
    }
    element('productView').classList.add('hidden');
    const context = vm.createContext({
        AbortController, Headers, URL, console,
        document: {
            cookie: '', hidden: false,
            getElementById: element, createElement: () => node(),
            querySelectorAll: () => [element('heroFace'), element('miniFace')],
            addEventListener() {}
        },
        window: {location: {origin: 'http://localhost:8000', assign() {}}, addEventListener() {}, open() {}},
        api: {
            request: async (url, options) => {calls.push({url, options}); return {};},
            setImage(image, value) {image.src = value;},
            image: value => value
        },
        setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
        clearTimeout(id) { timers.delete(id); },
        setInterval(fn) { timers.set(++timerId, fn); return timerId; },
        clearInterval(id) { timers.delete(id); }
    });
    vm.runInContext(read(script), context);
    return {context, element, calls, timers, run: source => vm.runInContext(source, context)};
}

const product = codigo => ({
    id: 1, codigo, nombre: 'Pollera ' + codigo, descripcion: 'Descripción', talla: 'M',
    precio_base: 100, precio_final: 80, rebaja: 80, incluye_sombrero: true, incluye_manta: false
});

test('returning home cancels generation, stops audio and unlocks detection', () => {
    const h = harness();
    h.run("detectionEnabled=true; phase='speaking'; requestController=new AbortController();");
    const controller = h.run('requestController');
    h.run('volverInicio()');
    assert.equal(controller.signal.aborted, true);
    assert.equal(h.run('phase'), 'idle');
    assert.equal(h.element('robotAudio').paused, true);
    assert.equal(h.element('robotAudio').onended, null);
    assert.equal(h.element('productView').classList.contains('hidden'), true);
    assert.ok(h.calls.some(call => call.url === '/api/audio/unlock'));
});

test('rejected audio playback returns to idle and releases the lock', async () => {
    const h = harness();
    h.run('detectionEnabled=true');
    h.element('robotAudio').play = async () => {throw new Error('autoplay blocked');};
    await h.run("playAudioFromUrl('/audio/fixture.mp3')");
    assert.equal(h.run('phase'), 'idle');
    assert.match(h.element('errorPanel').textContent, /voz no está disponible/);
    assert.ok(h.calls.some(call => call.url === '/api/audio/unlock'));
    assert.equal(h.timers.size, 0);
});

test('missing voice retains response text and resumes idle', async () => {
    const h = harness();
    await h.run("applySpeech({text:'Precio: S/ 80.00', audio_url:null}, sequence)");
    assert.equal(h.element('assistantText').textContent, 'Precio: S/ 80.00');
    assert.equal(h.run('phase'), 'idle');
});

test('late results cannot replace a newer product', async () => {
    const h = harness();
    let resolveA;
    const waitingA = new Promise(resolve => {resolveA = resolve;});
    h.context.api.request = async url => {
        if (url === '/api/polleras/A') return waitingA;
        if (url === '/api/polleras/B') return product('B');
        if (url === '/api/audio/detalles/B') return {text: 'Product B', audio_url: null};
        return {};
    };
    h.element('codigoInput').value = 'A';
    const first = h.run('buscarPollera()');
    h.element('codigoInput').value = 'B';
    await h.run('buscarPollera()');
    resolveA(product('A'));
    await first;
    assert.equal(h.run('currentProduct.codigo'), 'B');
    assert.equal(h.element('assistantText').textContent, 'Product B');
});

test('an offer request failure releases detection and request state', async () => {
    const h = harness();
    h.run('detectionEnabled=true');
    h.context.api.request = async (url, options) => {
        h.calls.push({url, options});
        if (url === '/api/check_interest') return {state:'running',interested:true};
        if (url === '/api/audio/ofertas') throw new Error('offline');
        return {};
    };
    await h.run('pollInterest()');
    assert.equal(h.run('phase'), 'idle');
    assert.equal(h.run('interestPending'), false);
    assert.ok(h.calls.some(call => call.url === '/api/audio/unlock'));
});

test('microphone interrupts an in-flight response', () => {
    const h = harness();
    h.run("phase='thinking'; requestController=new AbortController(); recognition={start(){},abort(){}};");
    const controller = h.run('requestController');
    h.run('startMic()');
    assert.equal(controller.signal.aborted, true);
    assert.equal(h.run('phase'), 'listening');
});

test('admin inventory treats malicious product content as text', () => {
    const h = harness('admin.js');
    h.context.fixture = {...product('X'), nombre:'<img src=x onerror=alert(1)>', codigo:'<script>bad</script>'};
    const card = h.run('productCard(fixture)');
    const body = card.children[1];
    assert.equal(body.children[0].textContent,'<script>bad</script>');
    assert.equal(body.children[1].textContent,'<img src=x onerror=alert(1)>');
});

test('image sources reject foreign URLs and normalized traversal', () => {
    const h = harness('api.js');
    for (const source of ['https://evil.example/x.jpg','javascript:alert(1)','/static/img/../../admin/login']) {
        h.context.source = source;
        assert.equal(h.run('api.image(source)'),'/static/img/default.svg');
    }
    assert.equal(h.run("api.image('/media/abc.jpg')"),'http://localhost:8000/media/abc.jpg');
});

test('administrative requests carry CSRF and same-origin credentials', async () => {
    const h = harness('api.js');
    h.context.document.cookie = 'iapolleras_csrf=fixture-token';
    let sent;
    h.context.fetch = async (url, options) => {
        sent = options;
        return {ok: true, json: async () => ({ok:true})};
    };
    await h.run("api.request('/api/admin/logout',{method:'POST'})");
    assert.equal(sent.headers.get('X-CSRF-Token'),'fixture-token');
    assert.equal(sent.credentials, 'same-origin');
    assert.equal(h.timers.size, 0);
});

test('setMood updates face classes with personality mood', () => {
    const h = harness();
    h.run("setMood('alegre')");
    assert.equal(h.element('heroFace').classList.contains('mood-alegre'), true);
    assert.equal(h.element('miniFace').classList.contains('mood-alegre'), true);
    h.run("setMood('entusiasmada')");
    assert.equal(h.element('heroFace').classList.contains('mood-alegre'), false);
    assert.equal(h.element('heroFace').classList.contains('mood-entusiasmada'), true);
});

test('product conversation routes to /api/conversacion and farewell navigates home', async () => {
    const h = harness();
    h.run("currentProduct = {codigo: 'TEST01', nombre: 'Test', precio_final: 80, precio_base: 100};");
    h.element('productView').classList.remove('hidden');
    h.context.api.request = async (url, options) => {
        h.calls.push({url, options});
        if (url === '/api/conversacion') {
            return {
                text: 'Gracias por visitarnos!',
                audio_url: null,
                mood: 'despedida',
                action: 'farewell'
            };
        }
        return {};
    };
    await h.run("enviarPreguntaConversacion('muchas gracias chau')");
    const convCall = h.calls.find(c => c.url === '/api/conversacion');
    assert.ok(convCall, 'Must call /api/conversacion');
    assert.match(convCall.options.body, /TEST01/);
    assert.equal(h.element('productView').classList.contains('hidden'), true);
    assert.equal(h.run('currentProduct'), null);
});

test('gallery autoplay cycles multiple photos and stops when returning home', () => {
    const h = harness();
    h.run("setupGallery(['/media/img1.jpg', '/media/img2.jpg', '/media/img3.jpg'])");
    assert.equal(h.run('currentProductImages.length'), 3);
    assert.ok(h.run('galleryAutoTimer !== null'), 'Autoplay timer must be active for 3 photos');
    
    // Check initial image
    assert.equal(h.run('currentImageIndex'), 0);
    // Simulate one autoplay step
    h.run('updateGalleryView(currentImageIndex + 1)');
    assert.equal(h.run('currentImageIndex'), 1);
    assert.equal(h.element('resImagen').src, '/media/img2.jpg');
    
    // Cycle to 3rd
    h.run('updateGalleryView(currentImageIndex + 1)');
    assert.equal(h.run('currentImageIndex'), 2);
    // Cycle wraps around to 1st
    h.run('updateGalleryView(currentImageIndex + 1)');
    assert.equal(h.run('currentImageIndex'), 0);
    assert.equal(h.element('resImagen').src, '/media/img1.jpg');

    // Single photo product should NOT start autoplay
    h.run("setupGallery(['/media/single.jpg'])");
    assert.equal(h.run('galleryAutoTimer'), null, 'Autoplay timer must NOT run for single photo');

    // Returning home stops autoplay
    h.run("setupGallery(['/media/a.jpg', '/media/b.jpg'])");
    assert.ok(h.run('galleryAutoTimer !== null'));
    h.run('volverInicio()');
    assert.equal(h.run('galleryAutoTimer'), null, 'volverInicio must clear gallery timer');
});

test('admin inventory renders rental buttons and status badges correctly', () => {
    const h = harness('admin.js');
    
    // Available product
    h.context.fixture = {...product('34TM'), estado: 'DISPONIBLE'};
    const cardAvailable = h.run('productCard(fixture)');
    const bodyAv = cardAvailable.children[1];
    const statusAv = bodyAv.children[2];
    assert.equal(statusAv.children[0].textContent, 'DISPONIBLE');
    assert.equal(statusAv.children[0].className, 'badge-disponible');
    const actionsAv = bodyAv.children[4];
    assert.equal(actionsAv.children[2].textContent, 'Marcar alquilada');
    assert.equal(actionsAv.children[2].className, 'btn-rental-rent btn-sm');

    // Rented product
    h.context.fixture = {...product('88XL'), estado: 'ALQUILADA', fecha_alquiler: '2026-10-15', fecha_devolucion_estimada: '2026-10-20'};
    const cardRented = h.run('productCard(fixture)');
    const bodyRent = cardRented.children[1];
    const statusRent = bodyRent.children[2];
    assert.equal(statusRent.children[0].textContent, 'ALQUILADA');
    assert.equal(statusRent.children[0].className, 'badge-alquilada');
    const rentalDetails = bodyRent.children[3];
    assert.match(rentalDetails.textContent, /Alquiler: 2026-10-15/);
    const actionsRent = bodyRent.children[5];
    assert.equal(actionsRent.children[2].textContent, 'Marcar disponible');
    assert.equal(actionsRent.children[2].className, 'btn-rental-return btn-sm');
});

