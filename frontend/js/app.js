import { setUnauthorizedHandler } from './api.js';
import { createAuth } from './auth.js';
import { createChat } from './chat.js';
import { createStudentData } from './student-data.js';
import { clearSession, getToken, isGuest, enterGuest, leaveGuest } from './session.js';
import { loadSemesters, resetSemesters } from './semester.js';

const chat = createChat({ onLoginRequired: () => showLogin('登录后即可开始对话') });
const studentData = createStudentData();
const auth = createAuth({
  onLogin: () => openSession(),
  onLogout: () => showLogin(),
  onSkip: () => showGuest(),
});

function showLogin(message = '') {
  clearSession();
  chat.reset();
  studentData.reset();
  resetSemesters();
  auth.showLogin(message);
}

async function openSession() {
  leaveGuest();
  auth.showChat();
  try {
    await loadSemesters();
    if (!getToken()) return;
    await chat.open();
    chat.focus();
  } catch (error) {
    if (error.name !== 'AbortError' && getToken()) document.getElementById('conversation-status').textContent = error.message;
  }
}

function showGuest() {
  clearSession();
  enterGuest();
  studentData.reset();
  resetSemesters();
  auth.showChat({ guest: true });
  chat.preview();
}

function requireLogin(message) {
  if (getToken()) return false;
  showLogin(message);
  return true;
}

setUnauthorizedHandler(showLogin);
// A login/logout in another tab invalidates this tab's outstanding UI work.
window.addEventListener('storage', event => {
  if (event.key !== 'cc_token' && event.key !== 'cc_user' && event.key !== null) return;
  chat.reset();
  studentData.reset();
  resetSemesters();
  if (getToken()) { openSession(); }
  else if (isGuest()) showGuest();
  else auth.showLogin('登录状态已在其他页面改变，请重新登录');
});
const bind = (id, callback) => document.getElementById(id).addEventListener('click', callback);
bind('login-submit', () => auth.submit('login'));
bind('register-submit', () => auth.submit('register'));
bind('login-skip', () => auth.skip());
bind('logout', () => getToken() ? auth.logout() : showLogin());
bind('send', () => chat.send());
bind('confirm-yes', () => chat.decide(true));
bind('confirm-no', () => chat.decide(false));
bind('save-course', () => studentData.saveCourse());
bind('save-grade', () => studentData.saveGrade());
document.querySelectorAll('[data-action="toggle-data"]').forEach(button => {
  button.addEventListener('click', () => {
    if (!requireLogin('登录后即可查看和管理你的课程与成绩')) studentData.toggle();
  });
});

document.getElementById('database-link').addEventListener('click', event => {
  if (!getToken()) {
    event.preventDefault();
    showLogin('登录后即可使用数据浏览器');
  }
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

if (getToken()) { openSession(); }
else if (isGuest()) { showGuest(); }
else showLogin();
