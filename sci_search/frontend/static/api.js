let csrfToken = null;

export async function initializeSession() {
  const session = await request('/api/v1/session');
  csrfToken = session.csrf_token;
  return session;
}

export async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  if (options.body && typeof options.body !== 'string') {
    headers.set('Content-Type', 'application/json');
    options = {...options, body: JSON.stringify(options.body)};
  }
  const response = await fetch(path, {...options, method, headers, credentials: 'same-origin'});
  if (response.status === 401) {
    window.location.assign('/auth/login');
    throw new Error('Authentication required');
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
}

export function setStatus(message, kind = 'info') {
  const target = document.getElementById('global-status');
  target.textContent = message;
  target.classList.toggle('error', kind === 'error');
}
