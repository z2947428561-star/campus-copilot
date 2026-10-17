import { requestJSON, streamChat } from './api.js';
import { getUser } from './session.js';

export function createChat() {
  const container = document.getElementById('chat');
  const input = document.getElementById('input');
  const sendButton = document.getElementById('send');
  const confirmation = document.getElementById('confirm-bar');
  const selector = document.getElementById('conversation-select');
  const status = document.getElementById('conversation-status');
  const newButton = document.getElementById('new-conversation');
  const refreshButton = document.getElementById('refresh-conversation');
  const yesButton = document.getElementById('confirm-yes');
  const noButton = document.getElementById('confirm-no');
  let busy = false;
  let loading = false;
  let pending = [];
  let checkpointId = null;
  let conversationId = null;
  let controller = null;
  let generation = 0;
  let running = false;
  let exhausted = false;
  let ready = false;
  let pollTimer = null;
  const selectionKey = () => 'cc_conversation:' + getUser();

  function controls() {
    sendButton.disabled = busy || loading || running || exhausted || !ready || !conversationId || pending.length > 0;
    input.disabled = sendButton.disabled;
    selector.disabled = newButton.disabled = refreshButton.disabled = busy || loading;
    yesButton.disabled = busy || loading || running || !ready || !pending.length ||
      pending.some(action => !action.allowed_decisions.includes('approve'));
    noButton.disabled = busy || loading || running || !ready || !pending.length ||
      pending.some(action => !action.allowed_decisions.includes('reject'));
  }

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

  function renderPending() {
    confirmation.style.display = pending.length ? 'flex' : 'none';
    document.getElementById('confirm-desc').textContent = pending.map((action, index) =>
      `${index + 1}. ${action.description || '敏感操作需要确认'}\n${action.tool}(${JSON.stringify(action.args)})`
    ).join('\n\n');
    yesButton.textContent = pending.length > 1 ? '确认全部执行' : '确认执行';
    noButton.textContent = pending.length > 1 ? '拒绝全部操作' : '取消操作';
    controls();
  }

  function clearMessages() {
    container.querySelectorAll('.msg').forEach(node => node.remove());
    container.classList.remove('has-messages');
  }

  async function open(wanted = null) {
    if (busy) return;
    clearTimeout(pollTimer);
    controller?.abort();
    const current = new AbortController();
    controller = current;
    const version = ++generation;
    loading = true;
    ready = false;
    controls();
    status.textContent = '正在读取会话…';
    try {
      const options = { signal: current.signal };
      const { conversations } = await requestJSON('/api/conversations', options);
      if (version !== generation) return;
      selector.replaceChildren();
      for (const item of conversations) {
        const option = document.createElement('option');
        option.value = item.id;
        const date = item.created_at ? ' · ' + new Date(item.created_at * 1000).toLocaleString() : '';
        option.textContent = item.title + date;
        selector.appendChild(option);
      }
      wanted ||= sessionStorage.getItem(selectionKey());
      conversationId = conversations.some(item => item.id === wanted) ? wanted : conversations[0]?.id;
      selector.value = conversationId;
      sessionStorage.setItem(selectionKey(), conversationId);
      clearMessages();
      pending = [];
      checkpointId = null;
      renderPending();
      const state = await requestJSON('/api/conversations/' + encodeURIComponent(conversationId), options);
      if (version !== generation) return;
      for (const message of state.messages) addMessage(message.role === 'user' ? 'me' : 'bot', message.text);
      pending = state.pending;
      checkpointId = state.checkpoint_id;
      running = state.running;
      exhausted = state.exhausted;
      ready = true;
      renderPending();
      status.textContent = running ? '该会话仍在处理请求，完成后会自动恢复。也可以新建会话。'
        : pending.length ? '请处理待确认操作，或新建会话。'
        : exhausted ? '当前会话额度已用完，请新建会话；原记录仍保留。' : '';
      if (running) pollTimer = setTimeout(() => open(conversationId), 1500);
    } catch (error) {
      if (version === generation && error.name !== 'AbortError') status.textContent = error.message;
    } finally {
      if (version === generation) { loading = false; controller = null; controls(); }
    }
  }

  async function createConversation() {
    if (busy || loading) return;
    const version = generation;
    const current = new AbortController();
    controller = current;
    loading = true;
    controls();
    try {
      const item = await requestJSON('/api/conversations', { method: 'POST', signal: current.signal });
      if (version === generation) await open(item.id);
    } catch (error) {
      if (version === generation && error.name !== 'AbortError') status.textContent = error.message;
    } finally {
      if (version === generation) { loading = false; controls(); }
    }
  }

  async function runTurn(body) {
    const current = new AbortController();
    controller = current;
    const version = generation;
    busy = true;
    clearTimeout(pollTimer);
    status.textContent = '';
    pending = [];
    renderPending();
    const message = addMessage('bot', '', true);
    const text = message.firstChild;
    const cursor = message.lastChild;
    try {
      await streamChat({ ...body, conversation_id: conversationId, checkpoint_id: checkpointId }, event => {
        if (controller !== current) return;
        if (event.type === 'token') text.textContent += event.text;
        else if (event.type === 'interrupt') {
          pending.push(event);
          checkpointId = event.checkpoint_id;
        } else if (event.type === 'error' || event.type === 'limit') status.textContent = event.message;
        container.scrollTop = container.scrollHeight;
      }, { signal: current.signal });
    } catch (error) {
      if (version === generation && error.name !== 'AbortError') status.textContent = error.message;
    } finally {
      cursor.remove();
      if (!text.textContent) message.remove();
      if (version === generation) {
        controller = null;
        busy = false;
        const notice = status.textContent;
        await open(conversationId);
        if (notice && version + 1 === generation) {
          status.textContent = [notice, status.textContent].filter(Boolean).join(' ');
        }
        input.focus();
      }
    }
  }

  async function send(question) {
    if (busy || loading || running || exhausted || !ready || !conversationId || pending.length) return;
    const text = (question ?? input.value).trim();
    if (!text) return;
    input.value = '';
    addMessage('me', text);
    await runTurn({ message: text });
  }

  async function decide(approved) {
    if (busy || loading || running || !ready || !pending.length) return;
    const type = approved ? 'approve' : 'reject';
    if (pending.some(action => !action.allowed_decisions.includes(type))) return;
    await runTurn({ decisions: pending.map(() => ({ type })) });
  }

  function reset() {
    generation++;
    clearTimeout(pollTimer);
    controller?.abort();
    controller = null;
    busy = loading = false;
    running = exhausted = ready = false;
    pending = [];
    conversationId = checkpointId = null;
    selector.replaceChildren();
    status.textContent = '';
    input.value = '';
    clearMessages();
    renderPending();
  }

  selector.addEventListener('change', () => open(selector.value));
  newButton.addEventListener('click', createConversation);
  refreshButton.addEventListener('click', () => open(conversationId));
  controls();
  return { send, decide, reset, open, focus: () => input.focus() };
}
