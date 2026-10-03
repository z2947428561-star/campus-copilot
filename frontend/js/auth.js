import { requestJSON } from './api.js';
import { clearSession, getUser, saveSession } from './session.js';

export function createAuth({ onLogin, onLogout }) {
  const mask = document.getElementById('login-mask');
  const username = document.getElementById('login-user');
  const password = document.getElementById('login-pass');
  const error = document.getElementById('login-err');
  const buttons = [document.getElementById('login-submit'), document.getElementById('register-submit')];
  let busy = false;

  function showLogin(message = '') {
    mask.classList.add('show');
    document.querySelector('.app-shell').inert = true;
    error.textContent = message;
    password.value = '';
    username.focus();
  }

  function showChat() {
    mask.classList.remove('show');
    document.querySelector('.app-shell').inert = false;
    document.getElementById('who').textContent = getUser();
  }

  async function submit(kind) {
    if (busy) return;
    const user = username.value.trim();
    const pass = password.value;
    error.textContent = '';
    if (kind === 'register') {
      if (!/^[A-Z]{3}[0-9]{2}(?:0[1-9]|1[0-2])[0-9]{3}$/.test(user)) {
        error.textContent = '用户名需为 3 位大写字母 + 7 位数字';
        username.focus();
        return;
      }
      if (pass.length < 8 || !/[A-Za-z]/.test(pass) || !/[0-9]/.test(pass)) {
        error.textContent = '密码至少 8 位，且同时包含字母和数字';
        password.focus();
        return;
      }
    }
    busy = true;
    buttons.forEach(button => { button.disabled = true; });
    try {
      const data = await requestJSON('/api/' + kind, {
        method: 'POST', authenticated: false, body: { username: user, password: pass },
      });
      saveSession(data.token, data.user_id);
      password.value = '';
      onLogin();
    } catch (exception) {
      error.textContent = kind === 'register' && exception.status
        ? '注册失败，请检查用户名和密码要求，或用户名是否已注册'
        : exception.message;
    } finally {
      busy = false;
      buttons.forEach(button => { button.disabled = false; });
    }
  }

  async function logout() {
    try { await requestJSON('/api/logout', { method: 'POST' }); } catch { /* Clear local state regardless. */ }
    clearSession();
    onLogout();
  }

  return { showLogin, showChat, submit, logout };
}
