let csrfToken = null;
let signingOut = false;
const pendingRequests = new Set();

export function beginLogout() {
  signingOut = true;
  for (const controller of pendingRequests) controller.abort();
  window.dispatchEvent(new Event('workspace-logout'));
}

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

export async function initializeSession() {
  const session = await request('/api/v1/session');
  csrfToken = session.csrf_token;
  return session;
}

export async function request(path, options = {}) {
  if (signingOut && path !== '/api/v1/session/logout') throw new DOMException('Signing out', 'AbortError');
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  if (options.body && typeof options.body !== 'string') {
    headers.set('Content-Type', 'application/json');
    options = {...options, body: JSON.stringify(options.body)};
  }
  const controller = new AbortController();
  const externalSignal = options.signal;
  const abort = () => controller.abort();
  if (externalSignal?.aborted) controller.abort();
  else externalSignal?.addEventListener('abort', abort, {once: true});
  pendingRequests.add(controller);
  let response;
  try {
    response = await fetch(path, {...options, signal: controller.signal, method, headers, credentials: 'same-origin'});
  } finally {
    pendingRequests.delete(controller);
    externalSignal?.removeEventListener('abort', abort);
  }
  if (response.status === 401) {
    if (window.location.pathname === '/app') sessionStorage.setItem('research-return-url', window.location.pathname + window.location.search);
    window.location.assign('/auth/login');
    throw new Error('Authentication required');
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.detail || `Request failed (${response.status})`, response.status, payload);
  }
  if (response.status === 204) return null;
  return response.json();
}

export function setStatus(message, kind = 'info') {
  const target = document.getElementById('global-status');
  target.textContent = message;
  target.classList.toggle('error', kind === 'error');
}
