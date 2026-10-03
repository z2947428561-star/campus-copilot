import { streamChat } from './api.js';

export function createChat() {
  const container = document.getElementById('chat');
  const input = document.getElementById('input');
  const sendButton = document.getElementById('send');
  const confirmation = document.getElementById('confirm-bar');
  let busy = false;
  let pendingResume = false;
  let controller = null;

  function addMessage(kind, text = '', withCursor = false) {
    container.classList.add('has-messages');
    const node = document.createElement('div');
    node.className = 'msg ' + kind;
    node.appendChild(document.createTextNode(text));
    if (withCursor) {
      const cursor = document.createElement('span');
      cursor.className = 'cursor';
      node.appendChild(cursor);
    }
    container.appendChild(node);
    container.scrollTop = container.scrollHeight;
    return node;
  }

  async function runTurn(body) {
    const current = new AbortController();
    controller = current;
    busy = true;
    sendButton.disabled = true;
    const message = addMessage('bot', '', true);
    const text = message.firstChild;
    const cursor = message.lastChild;
    let interrupted = false;
    try {
      await streamChat(body, event => {
        if (controller !== current) return;
        if (event.type === 'token') text.textContent += event.text;
        else if (event.type === 'interrupt') {
          interrupted = true;
          document.getElementById('confirm-desc').textContent =
            '⚠ ' + (event.description || '敏感操作需要确认') + '\n即将执行:'
            + event.tool + '(' + JSON.stringify(event.args) + ')';
          confirmation.style.display = 'flex';
        } else if (event.type === 'error') text.textContent += '\n[出错了] ' + event.message;
        container.scrollTop = container.scrollHeight;
      }, { signal: current.signal });
      if (controller === current) pendingResume = interrupted;
    } catch (error) {
      if (controller === current && error.name !== 'AbortError') {
        text.textContent += '\n[连接失败] ' + error.message;
      }
    } finally {
      cursor.remove();
      if (!text.textContent) message.remove();
      if (controller === current) {
        controller = null;
        busy = false;
        sendButton.disabled = false;
        input.focus();
      }
    }
  }

  async function send(question) {
    if (busy) return;
    const text = (question ?? input.value).trim();
    if (!text) return;
    input.value = '';
    addMessage('me', text);
    await runTurn({ message: text });
  }

  async function decide(approved) {
    if (busy || !pendingResume) return;
    pendingResume = false;
    confirmation.style.display = 'none';
    if (!approved) addMessage('sys', '已拒绝该敏感操作');
    await runTurn({ resume: approved });
  }

  function reset() {
    controller?.abort();
    controller = null;
    busy = pendingResume = false;
    sendButton.disabled = false;
    input.value = '';
    container.querySelectorAll('.msg').forEach(node => node.remove());
    container.classList.remove('has-messages');
    confirmation.style.display = 'none';
  }

  return { send, decide, reset, focus: () => input.focus() };
}
