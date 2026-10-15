document.addEventListener('DOMContentLoaded', () => {
    try { localStorage.removeItem('admin_token'); } catch (_) {}
    document.getElementById('login-form').addEventListener('submit', async event => {
        event.preventDefault();
        const button = event.target.querySelector('button');
        const error = document.getElementById('error-msg');
        button.disabled = true;
        error.style.display = 'none';
        try {
            await api.request('/api/admin/login', {method: 'POST', body: new FormData(event.target)});
            window.location.assign('/admin/dashboard');
        } catch (failure) {
            error.textContent = failure.name === 'AbortError' ? 'La conexión tardó demasiado. Intenta nuevamente.' : failure.message;
            error.style.display = 'block';
        } finally {
            button.disabled = false;
        }
    });
});
