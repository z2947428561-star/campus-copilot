import { requestJSON, streamChat } from './api.js';
import { getUser } from './session.js';

export function createChat() {
  const container = document.getElementById('chat');
  const input = document.getElementById('input');
  const sendButton = document.getElementById('send');
  const confirmation = document.getElementById('confirm-bar');
  let busy = false;
  let pendingResume = false;
  let controller = null;
  let conversationId = null;
  let loading = false;
  let generation = 0;
  const selector = document.getElementById('conversation-select');
  const status = document.getElementById('conversation-status');
  const selectionKey = () => 'cc_conversation:' + getUser();

  async function open(conversation = null) {
    if (busy) return;
    const version = ++generation;
    loading = true;
    sendButton.disabled = true;
    status.textContent = '正在读取会话…';
    try {
      const { conversations } = await requestJSON('/api/conversations');
      if (version !== generation) return;
      selector.replaceChildren();
      for (const item of conversations) {
        const option = document.createElement('option');
        option.value = item.id;
        const date = item.created_at ? ' · ' + new Date(item.created_at * 1000).toLocaleString() : '';
        option.textContent = item.title + date;
        selector.appendChild(option);
      }
      const wanted = conversation || sessionStorage.getItem(selectionKey());
      conversationId = conversations.some(item => item.id === wanted) ? wanted : conversations[0]?.id;
      selector.value = conversationId;
      sessionStorage.setItem(selectionKey(), conversationId);
      container.querySelectorAll('.msg').forEach(node => node.remove());
      container.classList.remove('has-messages');
      pendingResume = false;
      confirmation.style.display = 'none';
      status.textContent = '';
    } catch (error) {
      if (version === generation) status.textContent = error.message;
    } finally {
      if (version === generation) { loading = false; sendButton.disabled = !conversationId; }
    }
  }

  async function createConversation() {
    if (busy || loading) return;
    loading = true;
    try {
      const version = generation;
      const item = await requestJSON('/api/conversations', { method: 'POST' });
      if (version === generation) await open(item.id);
    } catch (error) { status.textContent = error.message; }
    finally { loading = false; }
  }

  selector.addEventListener('change', () => open(selector.value));
  document.getElementById('new-conversation').addEventListener('click', createConversation);
  document.getElementById('refresh-conversation').addEventListener('click', () => open(conversationId));

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
      await streamChat({ ...body, conversation_id: conversationId }, event => {
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
    if (busy || loading || !conversationId) return;
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
    generation++;
    conversationId = null;
    loading = false;
    selector.replaceChildren();
    status.textContent = '';
    controller?.abort();
    controller = null;
    busy = pendingResume = false;
    sendButton.disabled = false;
    input.value = '';
    container.querySelectorAll('.msg').forEach(node => node.remove());
    container.classList.remove('has-messages');
    confirmation.style.display = 'none';
  }

  return { send, decide, reset, open, focus: () => input.focus() };
}
