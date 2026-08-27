import {initializeSession, request} from './api.js';

export async function initializeAuth() {
  const session = await initializeSession();
  document.getElementById('account-name').textContent = session.user_id;
  document.getElementById('logout-button').addEventListener('click', async () => {
    await request('/api/v1/session/logout', {method: 'POST'});
    window.location.assign('/auth/login');
  });
}
