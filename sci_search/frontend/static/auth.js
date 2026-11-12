import {beginLogout, initializeSession, request} from './api.js';

export async function initializeAuth() {
  const returnUrl = sessionStorage.getItem('research-return-url');
  if (returnUrl && returnUrl.startsWith('/app?') && !window.location.search) window.history.replaceState({}, '', returnUrl);
  sessionStorage.removeItem('research-return-url');
  const session = await initializeSession();
  document.getElementById('account-name').textContent = session.user_id;
  document.getElementById('logout-button').addEventListener('click', async () => {
    beginLogout();
    await request('/api/v1/session/logout', {method: 'POST'});
    window.location.assign('/auth/login');
  });
  document.getElementById('logout-button').disabled = false;
}
