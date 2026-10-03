// Keep the existing storage keys so migration preserves local login sessions.
export const getToken = () => localStorage.getItem('cc_token') || '';
export const getUser = () => localStorage.getItem('cc_user') || '';

export function saveSession(token, user) {
  localStorage.setItem('cc_token', token);
  localStorage.setItem('cc_user', user);
}

export function clearSession() {
  localStorage.removeItem('cc_token');
  localStorage.removeItem('cc_user');
}
