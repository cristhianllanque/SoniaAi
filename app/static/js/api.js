const api = {
    csrf() {
        const item = document.cookie.split('; ').find(value => value.startsWith('iapolleras_csrf='));
        return item ? decodeURIComponent(item.split('=').slice(1).join('=')) : '';
    },
    async request(url, options = {}) {
        const controller = new AbortController();
        const cancel = () => controller.abort();
        const external = options.signal;
        if (external?.aborted) controller.abort();
        external?.addEventListener('abort', cancel, {once: true});
        const timeout = setTimeout(cancel, options.timeout || 45000);
        const headers = new Headers(options.headers || {});
        if (!['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())) {
            headers.set('X-CSRF-Token', this.csrf());
        }
        try {
            const response = await fetch(url, {...options, headers, signal: controller.signal, credentials: 'same-origin'});
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const error = new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo completar la solicitud.');
                error.status = response.status;
                throw error;
            }
            return data;
        } finally {
            clearTimeout(timeout);
            external?.removeEventListener('abort', cancel);
        }
    },
    image(value) {
        try {
            const url = new URL(value || '', window.location.origin);
            if (url.origin === window.location.origin && ['/media/', '/static/img/'].some(prefix => url.pathname.startsWith(prefix))) {
                return url.href;
            }
        } catch (_) {}
        return '/static/img/default.svg';
    },
    setImage(element, value) {
        element.onerror = () => {
            element.onerror = null;
            element.src = '/static/img/default.svg';
        };
        element.src = this.image(value);
    }
};
