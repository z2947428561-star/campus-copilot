// Keep the existing storage keys so migration preserves local login sessions.
export const getToken = () => localStorage.getItem('cc_token') || '';
export const getUser = () => localStorage.getItem('cc_user') || '';
export const isGuest = () => sessionStorage.getItem('cc_guest') === '1';
export const enterGuest = () => sessionStorage.setItem('cc_guest', '1');
export const leaveGuest = () => sessionStorage.removeItem('cc_guest');

export function saveSession(token, user) {
  leaveGuest();
  localStorage.setItem('cc_token', token);
  localStorage.setItem('cc_user', user);
}

export function clearSession() {
  leaveGuest();
  localStorage.removeItem('cc_token');
  localStorage.removeItem('cc_user');
}
