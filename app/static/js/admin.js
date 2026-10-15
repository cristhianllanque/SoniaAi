const inventory = new Map();
let inventoryOffset = 0;
let activeTab = 'inventory';
let inventoryBusy = false;
const byId = id => document.getElementById(id);

function message(text, success = false) {
    const box = byId('msg');
    box.textContent = text;
    box.className = 'message ' + (success ? 'success' : 'error');
    box.style.display = 'block';
}

function sessionError(error) {
    if (error.status === 401) window.location.assign('/admin/login');
    return error.message || 'No se pudo conectar con el servidor.';
}

function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll('.dashboard-section').forEach(section => section.classList.remove('active'));
    document.querySelectorAll('[data-tab]').forEach(button => button.classList.toggle('active', button.dataset.tab === tab));
    byId(tab + '-section').classList.add('active');
    if (tab !== 'monitor') byId('admin-webcam').removeAttribute('src');
    if (tab === 'inventory') cargarInventario();
    if (tab === 'monitor') cameraStatus();
}

async function logout() {
    try {
        await api.request('/api/admin/logout', {method: 'POST'});
        window.location.assign('/admin/login');
    } catch (error) {
        if (error.status === 401) window.location.assign('/admin/login');
        else message(sessionError(error));
    }
}

function newProduct() {
    byId('pollera-form').reset();
    byId('product-id').value = '';
    byId('form-title').textContent = 'Registrar nueva pollera';
    byId('save-btn').textContent = 'Registrar producto';
    byId('cancel-edit').hidden = true;
    byId('msg').style.display = 'none';
    for (const n of [1, 2, 3]) {
        const box = byId(`preview-${n}-box`);
        if (box) box.style.display = 'none';
        const chk = byId(`eliminar_imagen_${n}`);
        if (chk) chk.checked = false;
    }
}

function editProduct(item) {
    newProduct();
    byId('product-id').value = item.id;
    for (const field of ['codigo', 'nombre', 'descripcion', 'talla', 'precio_base', 'rebaja']) {
        byId(field).value = item[field];
    }
    for (const field of ['incluye_sombrero', 'incluye_manta']) byId(field).checked = item[field];
    const imgs = [item.imagen_url, item.imagen_url_2, item.imagen_url_3];
    for (let i = 0; i < 3; i++) {
        const url = imgs[i];
        const box = byId(`preview-${i + 1}-box`);
        const imgEl = byId(`preview-${i + 1}`);
        const chk = byId(`eliminar_imagen_${i + 1}`);
        if (box && imgEl) {
            if (url) {
                box.style.display = 'block';
                api.setImage(imgEl, url);
                if (chk) chk.checked = false;
            } else {
                box.style.display = 'none';
            }
        }
    }
    byId('form-title').textContent = 'Editar pollera';
    byId('save-btn').textContent = 'Guardar cambios';
    byId('cancel-edit').hidden = false;
    switchTab('add');
    byId('codigo').focus();
}

async function deleteProduct(item) {
    if (!window.confirm(`¿Estás seguro de eliminar "${item.nombre}" (${item.codigo})? Esta acción no se puede deshacer.`)) {
        return;
    }
    try {
        await api.request('/api/admin/polleras/' + item.id, {method: 'DELETE'});
        message(`Pollera ${item.codigo} eliminada correctamente.`, true);
        cargarInventario();
    } catch (error) {
        message(sessionError(error));
    }
}

function abrirModalAlquiler(item) {
    byId('rental-product-id').value = item.id;
    byId('rental-product-name').textContent = `Pollera: ${item.nombre} (${item.codigo})`;
    const today = new Date();
    const todayStr = today.toISOString().split('T')[0];
    const dev = new Date();
    dev.setDate(dev.getDate() + 5);
    const devStr = dev.toISOString().split('T')[0];
    byId('fecha_alquiler').value = todayStr;
    byId('fecha_devolucion_estimada').value = devStr;
    byId('rental-modal').style.display = 'block';
    byId('modal-backdrop').style.display = 'block';
}

function cerrarModalAlquiler() {
    byId('rental-modal').style.display = 'none';
    byId('modal-backdrop').style.display = 'none';
    byId('rental-form').reset();
}

async function confirmarAlquiler(event) {
    event.preventDefault();
    const id = byId('rental-product-id').value;
    const fAlq = byId('fecha_alquiler').value;
    const fDev = byId('fecha_devolucion_estimada').value;
    const data = new FormData();
    data.set('fecha_alquiler', fAlq);
    data.set('fecha_devolucion_estimada', fDev);
    try {
        await api.request('/api/admin/polleras/' + id + '/alquilar', {method: 'POST', body: data});
        cerrarModalAlquiler();
        message('Pollera marcada como alquilada.', true);
        cargarInventario();
    } catch (error) {
        message(sessionError(error));
    }
}

async function marcarDisponible(item) {
    if (!window.confirm(`¿Confirmas que la pollera "${item.nombre}" (${item.codigo}) regresó físicamente a la tienda?`)) {
        return;
    }
    try {
        await api.request('/api/admin/polleras/' + item.id + '/devolver', {method: 'POST'});
        message(`Pollera ${item.codigo} marcada como disponible.`, true);
        cargarInventario();
    } catch (error) {
        message(sessionError(error));
    }
}

function productCard(item) {
    const card = document.createElement('article');
    card.className = 'inventory-card';
    const image = document.createElement('img');
    image.className = 'card-img';
    image.alt = item.nombre;
    api.setImage(image, item.imagen_url);
    const body = document.createElement('div');
    body.className = 'card-body';
    const code = document.createElement('div');
    code.className = 'card-tag';
    code.textContent = item.codigo;
    const title = document.createElement('h3');
    title.className = 'card-title';
    title.textContent = item.nombre;
    const isRented = item.estado === 'ALQUILADA';
    const status = document.createElement('div');
    status.style.marginBottom = '8px';
    const badge = document.createElement('span');
    badge.className = isRented ? 'badge-alquilada' : 'badge-disponible';
    badge.textContent = isRented ? 'ALQUILADA' : 'DISPONIBLE';
    status.append(badge);

    let rentalDetails = null;
    if (isRented) {
        rentalDetails = document.createElement('div');
        rentalDetails.className = 'rental-info';
        const fAlq = item.fecha_alquiler || '—';
        const fDev = item.fecha_devolucion_estimada || '—';
        rentalDetails.textContent = `Alquiler: ${fAlq} | Retorno est.: ${fDev}`;
    }

    const price = document.createElement('p');
    price.className = 'card-price';
    price.textContent = 'S/ ' + Number(item.precio_final).toFixed(2);
    const actions = document.createElement('div');
    actions.className = 'card-actions';
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.className = 'btn-submit btn-sm';
    edit.textContent = 'Editar';
    edit.addEventListener('click', () => editProduct(item));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn-danger btn-sm';
    remove.textContent = 'Eliminar';
    remove.addEventListener('click', () => deleteProduct(item));

    const rentBtn = document.createElement('button');
    rentBtn.type = 'button';
    if (isRented) {
        rentBtn.className = 'btn-rental-return btn-sm';
        rentBtn.textContent = 'Marcar disponible';
        rentBtn.addEventListener('click', () => marcarDisponible(item));
    } else {
        rentBtn.className = 'btn-rental-rent btn-sm';
        rentBtn.textContent = 'Marcar alquilada';
        rentBtn.addEventListener('click', () => abrirModalAlquiler(item));
    }

    actions.append(edit, remove, rentBtn);
    if (rentalDetails) {
        body.append(code, title, status, rentalDetails, price, actions);
    } else {
        body.append(code, title, status, price, actions);
    }
    card.append(image, body);

    const allImages = item.imagenes || [item.imagen_url, item.imagen_url_2, item.imagen_url_3].filter(Boolean);
    if (allImages.length > 1) {
        const thumbBar = document.createElement('div');
        thumbBar.className = 'card-thumbs';
        allImages.forEach(url => {
            const thumb = document.createElement('img');
            thumb.className = 'card-thumb';
            thumb.alt = item.nombre;
            api.setImage(thumb, url);
            thumb.addEventListener('click', () => api.setImage(image, url));
            thumbBar.append(thumb);
        });
        card.append(thumbBar);
    }
    return card;
}

async function cargarInventario(append = false) {
    if (inventoryBusy) return;
    inventoryBusy = true;
    if (!append) {
        inventoryOffset = 0;
        inventory.clear();
        byId('inventory-container').replaceChildren();
    }
    byId('inventory-status').textContent = 'Cargando inventario…';
    try {
        const items = await api.request('/api/polleras/?skip=' + inventoryOffset + '&limit=100');
        for (const item of items) {
            inventory.set(item.id, item);
            byId('inventory-container').append(productCard(item));
        }
        inventoryOffset += items.length;
        byId('more-btn').hidden = items.length < 100;
        byId('inventory-status').textContent = inventory.size ? '' : 'No hay polleras registradas.';
    } catch (error) {
        byId('inventory-status').textContent = sessionError(error);
    } finally {
        inventoryBusy = false;
    }
}

async function cameraStatus() {
    if (activeTab !== 'monitor') return;
    try {
        const status = await api.request('/api/vision/status', {timeout: 5000});
        const running = ['starting', 'running'].includes(status.state);
        byId('camera-status').textContent = status.error || (running ? 'Detección activa. El video solo está disponible para administradores.' : 'Detección detenida.');
        if (running && !byId('admin-webcam').getAttribute('src')) byId('admin-webcam').src = '/api/video_feed';
        if (!running) byId('admin-webcam').removeAttribute('src');
    } catch (error) {
        byId('camera-status').textContent = sessionError(error);
    }
}

async function controlCamera(action) {
    try {
        await api.request('/api/vision/' + action, {method: 'POST'});
        await cameraStatus();
    } catch (error) {
        byId('camera-status').textContent = sessionError(error);
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    try { localStorage.removeItem('admin_token'); } catch (_) {}
    try {
        await api.request('/api/admin/me');
    } catch (error) {
        sessionError(error);
        return;
    }
    document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
        if (button.dataset.tab === 'add') newProduct();
        switchTab(button.dataset.tab);
    }));
    byId('logout-btn').addEventListener('click', logout);
    byId('cancel-edit').addEventListener('click', () => {newProduct(); switchTab('inventory');});
    byId('more-btn').addEventListener('click', () => cargarInventario(true));
    byId('start-camera').addEventListener('click', () => controlCamera('start'));
    byId('stop-camera').addEventListener('click', () => controlCamera('stop'));
    byId('pollera-form').addEventListener('submit', async event => {
        event.preventDefault();
        for (const name of ['imagen', 'imagen_2', 'imagen_3']) {
            const input = byId(name);
            const file = input && input.files ? input.files[0] : null;
            if (file && file.size > 5 * 1024 * 1024) {
                message('Cada imagen no debe superar 5 MB.');
                return;
            }
        }
        const data = new FormData(event.target);
        for (const name of ['incluye_sombrero', 'incluye_manta']) data.set(name, byId(name).checked ? 'true' : 'false');
        for (const name of ['eliminar_imagen_1', 'eliminar_imagen_2', 'eliminar_imagen_3']) {
            const el = byId(name);
            data.set(name, (el && el.checked) ? 'true' : 'false');
        }
        const id = byId('product-id').value;
        byId('save-btn').disabled = true;
        try {
            await api.request('/api/admin/polleras' + (id ? '/' + id : ''), {method: id ? 'PUT' : 'POST', body: data});
            newProduct();
            switchTab('inventory');
        } catch (error) {
            message(sessionError(error));
        } finally {
            byId('save-btn').disabled = false;
        }
    });

    const rentalForm = byId('rental-form');
    if (rentalForm) rentalForm.addEventListener('submit', confirmarAlquiler);
    const cancelRentBtn = byId('cancel-rental');
    if (cancelRentBtn) cancelRentBtn.addEventListener('click', cerrarModalAlquiler);
    const backdrop = byId('modal-backdrop');
    if (backdrop) backdrop.addEventListener('click', cerrarModalAlquiler);

    cargarInventario();
    const timer = setInterval(cameraStatus, 3000);
    window.addEventListener('pagehide', () => {
        clearInterval(timer);
        byId('admin-webcam').removeAttribute('src');
    }, {once: true});
});
