// Real-browser smoke test with isolated data, no camera and no external AI/voice.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname,'..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(),'iapolleras-browser-'));
const artifacts = path.join(root,'artifacts','review');
fs.mkdirSync(artifacts,{recursive:true});
const sleep = ms => new Promise(resolve => setTimeout(resolve,ms));
let server, browser, ws;
const errors = [];
let serial = 0;
const pending = new Map();

async function freePort() {
    const socket = net.createServer();
    await new Promise(resolve => socket.listen(0,'127.0.0.1',resolve));
    const port = socket.address().port;
    await new Promise(resolve => socket.close(resolve));
    return port;
}
async function until(check, label, timeout = 20000) {
    const end = Date.now()+timeout;
    while (Date.now()<end) {
        try { if (await check()) return; } catch (_) {}
        await sleep(100);
    }
    throw new Error('Timed out: '+label);
}
function send(method,params={}) {
    return new Promise((resolve,reject) => {
        const id = ++serial;
        pending.set(id,{resolve,reject});
        ws.send(JSON.stringify({id,method,params}));
    });
}
async function evaluate(expression) {
    const response = await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    return response.result.value;
}
async function visit(url) {
    await send('Page.navigate',{url});
    await until(() => evaluate('document.readyState === "complete"'),'page ready');
}
async function screenshot(name) {
    const result = await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    fs.writeFileSync(path.join(artifacts,name),Buffer.from(result.data,'base64'));
}
async function stop(child) {
    if (!child || child.exitCode !== null) return;
    const ended = new Promise(resolve => child.once('exit',resolve));
    child.kill();
    await Promise.race([ended,sleep(4000)]);
}
(async () => {
    try {
        const port = await freePort();
        const origin = 'http://127.0.0.1:'+port;
        let serverLog = '';
        server = spawn(path.join(root,'venv','Scripts','python.exe'),['-B',path.join(__dirname,'browser_fixture.py')],{
            cwd:root, windowsHide:true,
            env:{...process.env,PYTHONPATH:root,DATA_DIR:path.join(temporary,'data'),
                DATABASE_URL:'sqlite:///'+path.join(temporary,'test.db').replaceAll('\\','/'),
                SECRET_KEY:'browser-fixture-only-'.repeat(4),PRODUCTION:'false',COOKIE_SECURE:'false',
                ALLOWED_HOSTS:'127.0.0.1,localhost',IAPOLLERAS_BROWSER_TEST:'1',IAPOLLERAS_TEST_PORT:String(port)}
        });
        server.stderr.on('data',chunk => serverLog += chunk);
        await until(async () => {
            if (server.exitCode !== null) throw new Error(serverLog);
            return (await fetch(origin+'/api/health')).ok;
        },'test server');
        const executable = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
        const profile = path.join(temporary,'chrome');
        browser = spawn(executable,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--remote-debugging-port=0','--user-data-dir='+profile,'--window-size=1280,1000','about:blank'],
            {windowsHide:true,stdio:'ignore'});
        const activePort = path.join(profile,'DevToolsActivePort');
        await until(() => fs.existsSync(activePort),'browser debugger');
        const debugPort = fs.readFileSync(activePort,'utf8').split('\n')[0].trim();
        const pages = await (await fetch('http://127.0.0.1:'+debugPort+'/json/list')).json();
        ws = new WebSocket(pages.find(page => page.type==='page').webSocketDebuggerUrl);
        await new Promise((resolve,reject) => {ws.onopen=resolve;ws.onerror=reject;});
        ws.onmessage = event => {
            const data = JSON.parse(event.data);
            if (data.id && pending.has(data.id)) {
                const handlers = pending.get(data.id);
                pending.delete(data.id);
                if (data.error) handlers.reject(new Error(JSON.stringify(data.error)));
                else handlers.resolve(data.result);
            }
            if (data.method==='Runtime.exceptionThrown') errors.push(data.params.exceptionDetails.text);
        };
        await send('Page.enable');
        await send('Runtime.enable');
        await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
        await visit(origin+'/');
        assert.equal(await evaluate('Boolean(document.querySelector("#cameraFeed, #tryOnIndicator"))'),false);
        await evaluate('document.getElementById("codigoInput").value="34TM"; document.getElementById("searchBtn").click();');
        await until(() => evaluate('document.getElementById("assistantText").textContent.includes("80.00 soles")'),'product and readable speech');
        assert.equal(await evaluate('document.getElementById("assistantResponse").getClientRects().length'),0,'spoken transcript must stay hidden');
        assert.equal(await evaluate('document.getElementById("resPrecioFinal").textContent'),'80.00');
        assert.equal(await evaluate('document.getElementById("resEstado").textContent'),'DISPONIBLE');
        
        // Mejora 2: Verificar que flechas y chips están ocultos en modo autónomo
        assert.equal(await evaluate('document.getElementById("galleryPrev").classList.contains("hidden")'),true);
        assert.equal(await evaluate('document.getElementById("galleryNext").classList.contains("hidden")'),true);
        assert.equal(await evaluate('document.getElementById("quickChips").classList.contains("hidden")'),true);
        assert.ok(await evaluate('galleryAutoTimer !== null'),'Autoplay timer running for 3 images');

        // Captura en escritorio regular
        await screenshot('product-desktop.png');

        // Mejora 3: Emular pantalla de 7 pulgadas táctil (1024x600 - estándar Raspberry Pi)
        await send('Emulation.setDeviceMetricsOverride',{width:1024,height:600,deviceScaleFactor:1,mobile:false});
        await sleep(200);
        await screenshot('product-7inch-1024x600.png');

        // Emular pantalla de 7 pulgadas compacta (800x480 - DSI Raspberry Pi)
        await send('Emulation.setDeviceMetricsOverride',{width:800,height:480,deviceScaleFactor:1,mobile:false});
        await sleep(200);
        await screenshot('product-7inch-800x480.png');

        // Emular móvil vertical
        await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
        await sleep(100);
        await screenshot('product-mobile.png');
        assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'),'mobile overflow');
        await send('Emulation.clearDeviceMetricsOverride');

        // Mejora 1: Panel de administración y botones de alquiler
        await visit(origin+'/admin/login');
        await evaluate('document.getElementById("username").value="owner"; document.getElementById("password").value="browser-test-password"; document.querySelector("#login-form button").click();');
        await until(() => evaluate('location.pathname === "/admin/dashboard" && document.querySelectorAll(".inventory-card").length === 1'),'admin login and inventory');
        assert.equal(await evaluate('document.cookie.includes("iapolleras_session")'),false);

        // Verificar presencia de "Marcar alquilada" y badge "DISPONIBLE"
        assert.ok(await evaluate('document.querySelector(".btn-rental-rent")?.textContent.includes("Marcar alquilada")'),'Boton Marcar alquilada visible');
        assert.ok(await evaluate('document.querySelector(".badge-disponible")?.textContent.includes("DISPONIBLE")'),'Badge DISPONIBLE visible');
        await screenshot('admin-available.png');

        // Abrir modal de alquiler y confirmar
        await evaluate('document.querySelector(".btn-rental-rent").click();');
        await until(() => evaluate('document.getElementById("rental-modal").style.display === "block"'),'modal alquiler abierto');
        await evaluate('document.getElementById("confirm-rental").click();');

        // Verificar que el estado cambió a ALQUILADA y el botón ahora es "Marcar disponible"
        await until(() => evaluate('document.querySelector(".badge-alquilada")?.textContent.includes("ALQUILADA")'),'estado cambiado a ALQUILADA');
        assert.ok(await evaluate('document.querySelector(".btn-rental-return")?.textContent.includes("Marcar disponible")'),'Boton Marcar disponible visible');
        await screenshot('admin-rented.png');

        // Marcar como disponible con confirmación
        await evaluate('window.confirm = () => true; document.querySelector(".btn-rental-return").click();');
        await until(() => evaluate('document.querySelector(".badge-disponible")?.textContent.includes("DISPONIBLE")'),'estado devuelto a DISPONIBLE');
        assert.ok(await evaluate('document.querySelector(".btn-rental-rent")?.textContent.includes("Marcar alquilada")'),'Boton Marcar alquilada restaurado');
        await screenshot('admin-returned.png');

        // Editar precio
        await evaluate('document.querySelector(".inventory-card .btn-submit").click();');
        await evaluate('document.getElementById("rebaja").value="70.50"; document.getElementById("save-btn").click();');
        await until(() => evaluate('document.querySelector(".card-price")?.textContent.includes("70.50")'),'edit price');
        await screenshot('admin-desktop.png');

        assert.equal((await fetch(origin+'/api/video_feed')).status,401);
        assert.deepEqual(errors,[]);
        console.log(JSON.stringify({browser:'Chrome',checks:[
            'product search',
            'hidden transcript',
            'availability badge',
            'gallery autoplay timer',
            '7-inch 1024x600 layout',
            '7-inch 800x480 layout',
            'mobile width',
            'admin rental button "Marcar alquilada"',
            'rental modal flow',
            'admin status "ALQUILADA"',
            'admin return button "Marcar disponible"',
            'admin return confirmation to "DISPONIBLE"',
            'edit product',
            'private camera',
            'no JavaScript exceptions'
        ],artifacts}));
    } finally {
        ws?.close();
        await stop(browser);
        await stop(server);
        const target = path.resolve(temporary);
        if (path.dirname(target)!==path.resolve(os.tmpdir()) || !path.basename(target).startsWith('iapolleras-browser-')) {
            throw new Error('Refusing cleanup outside the test temporary directory.');
        }
        fs.rmSync(target,{recursive:true,force:true,maxRetries:10,retryDelay:300});
    }
})().catch(error => {console.error(error);process.exitCode=1;});
