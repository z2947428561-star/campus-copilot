import { setUnauthorizedHandler } from './api.js';
import { createAuth } from './auth.js';
import { createChat } from './chat.js';
import { createStudentData } from './student-data.js';
import { clearSession, getToken } from './session.js';

const chat = createChat();
const studentData = createStudentData();
const auth = createAuth({
  onLogin: () => { auth.showChat(); chat.open(); chat.focus(); },
  onLogout: () => showLogin(),
});

function showLogin(message = '') {
  clearSession();
  chat.reset();
  studentData.reset();
  auth.showLogin(message);
}

setUnauthorizedHandler(showLogin);
// A login/logout in another tab invalidates this tab's outstanding UI work.
window.addEventListener('storage', event => {
  if (event.key !== 'cc_token' && event.key !== 'cc_user' && event.key !== null) return;
  chat.reset();
  studentData.reset();
  if (getToken()) { auth.showChat(); chat.open(); }
  else auth.showLogin('登录状态已在其他页面改变，请重新登录');
});
const bind = (id, callback) => document.getElementById(id).addEventListener('click', callback);
bind('login-submit', () => auth.submit('login'));
bind('register-submit', () => auth.submit('register'));
bind('logout', () => auth.logout());
bind('send', () => chat.send());
bind('confirm-yes', () => chat.decide(true));
bind('confirm-no', () => chat.decide(false));
bind('save-course', () => studentData.saveCourse());
bind('save-grade', () => studentData.saveGrade());
document.querySelectorAll('[data-action="toggle-data"]').forEach(button => {
  button.addEventListener('click', () => studentData.toggle());
});
document.querySelectorAll('[data-question]').forEach(button => {
  button.addEventListener('click', () => chat.send(button.dataset.question));
});
document.getElementById('login-pass').addEventListener('keydown', event => {
  if (event.key === 'Enter') auth.submit('login');
});
document.getElementById('input').addEventListener('keydown', event => {
  if (event.key === 'Enter') chat.send();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && studentData.isOpen()) studentData.toggle();
});

if (getToken()) { auth.showChat(); chat.open(); chat.focus(); }
else showLogin();
