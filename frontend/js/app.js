import { setUnauthorizedHandler } from './api.js';
import { createAuth } from './auth.js';
import { createChat } from './chat.js';
import { createStudentData } from './student-data.js';
import { clearSession, getToken } from './session.js';

const chat = createChat();
const studentData = createStudentData();
const auth = createAuth({
  onLogin: () => { auth.showChat(); chat.focus(); },
  onLogout: () => showLogin(),
});

function showLogin(message = '') {
  clearSession();
  chat.reset();
  studentData.reset();
  auth.showLogin(message);
}

setUnauthorizedHandler(showLogin);
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

if (getToken()) { auth.showChat(); chat.focus(); }
else showLogin();
