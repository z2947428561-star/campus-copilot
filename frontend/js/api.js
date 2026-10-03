import { getToken } from './session.js';

let onUnauthorized = () => {};

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = 'GET', body, authenticated = true, signal } = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json' };
  if (authenticated && token) headers.Authorization = 'Bearer ' + token;
  const response = await fetch(path, {
    method, headers, signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let data = {};
    try { data = await response.json(); } catch { /* Non-JSON errors use HTTP status. */ }
    if (authenticated && response.status === 401 && token === getToken()) {
      onUnauthorized('登录已过期，请重新登录');
    }
    throw new ApiError(response.status,
      typeof data.detail === 'string' ? data.detail : '请求失败（HTTP ' + response.status + '）');
  }
  return response;
}

export async function requestJSON(path, options) {
  return (await request(path, options)).json();
}

export async function streamChat(body, onEvent, { signal } = {}) {
  const response = await request('/api/chat', { method: 'POST', body, signal });
  if (!response.body) throw new Error('浏览器未提供流式响应');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  function emit(frame) {
    const data = frame.split(/\r?\n/)
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).replace(/^ /, '')).join('\n');
    if (data) onEvent(JSON.parse(data));
  }

  function consume() {
    let separator;
    while ((separator = /\r?\n\r?\n/.exec(buffer))) {
      emit(buffer.slice(0, separator.index));
      buffer = buffer.slice(separator.index + separator[0].length);
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      consume();
    }
    buffer += decoder.decode();
    consume();
    if (buffer.trim()) emit(buffer);
  } finally {
    reader.releaseLock();
  }
}
