// Run against an isolated local app with playwright-cli run-code --filename=...
// Real APIs and checkpoint persistence; an offline fake model supplies deterministic replies.
async page => {
  await page.unrouteAll({ behavior: 'wait' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const ensure = (condition, message) => { if (!condition) throw new Error(message); };
  const username = 'TST2601' + String(Math.floor(Math.random() * 1000)).padStart(3, '0');
  await page.goto('http://127.0.0.1:18765/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.locator('#login-mask.show').waitFor();
  ensure(await page.locator('link[rel="stylesheet"]').count() === 1, 'Stylesheet missing');
  ensure(await page.locator('[onclick]').count() === 0, 'Inline event handlers remain');
  await page.locator('#login-user').fill('TST2613001');
  await page.locator('#login-pass').fill('Testpass123');
  await page.locator('#register-submit').click();
  ensure((await page.locator('#login-err').textContent()).includes('用户名'), 'Registration rule missing');
  await page.locator('#login-user').fill(username);
  await page.locator('#register-submit').click();
  await page.locator('#login-mask.show').waitFor({ state: 'hidden' });
  ensure(await page.locator('#who').textContent() === username, 'Registration session missing');

  await page.locator('#data-toggle').click();
  await page.locator('#data-panel.open').waitFor();
  await page.locator('#course-id').fill('CS101');
  await page.locator('#save-course').click();
  await page.waitForFunction(() => document.querySelector('#data-list').textContent.includes('CS101'));
  await page.locator('#grade-course').fill('CS101');
  await page.locator('#grade-point').fill('3.7');
  await page.locator('#grade-letter').fill('A-');
  await page.locator('#save-grade').click();
  await page.waitForFunction(() => document.querySelector('#data-list').textContent.includes('3.7'));
  await page.locator('#data-list button').last().click();
  await page.waitForFunction(() => !document.querySelector('#data-list').textContent.includes('3.7'));
  await page.locator('#data-list button').first().click();
  await page.waitForFunction(() => !document.querySelector('#data-list').textContent.includes('CS101'));
  await page.keyboard.press('Escape');
  await page.locator('#data-panel.open').waitFor({ state: 'hidden' });

  const ready = () => page.waitForFunction(() => !document.querySelector('#send').disabled);
  const newConversation = async () => {
    const old = await page.locator('#conversation-select').inputValue();
    await page.locator('#new-conversation').click();
    await page.waitForFunction(old => document.querySelector('#conversation-select').value !== old, old);
    await ready();
    return page.locator('#conversation-select').inputValue();
  };
  const send = async message => {
    await ready();
    await page.locator('#input').fill(message);
    await page.locator('#send').click();
  };
  await ready();
  const first = await newConversation();
  await send('第一段历史');
  await page.waitForFunction(() => document.querySelector('#chat').textContent.includes('中文流式测试通过：第一段历史'));
  await ready();
  await page.reload();
  await ready();
  ensure((await page.locator('#chat').textContent()).includes('第一段历史'), 'History lost on refresh');
  ensure(await page.locator('#conversation-select').inputValue() === first, 'Selected conversation lost');
  await newConversation();
  ensure(await page.locator('.msg').count() === 0, 'New conversation inherited messages');
  await page.locator('#conversation-select').selectOption(first);
  await ready();
  ensure((await page.locator('#chat').textContent()).includes('第一段历史'), 'Switch did not restore history');

  await newConversation();
  await send('双重确认 GPA');
  await page.locator('#confirm-yes').waitFor({ state: 'visible' });
  await page.waitForFunction(() => !document.querySelector('#confirm-yes').disabled);
  ensure((await page.locator('#confirm-desc').textContent()).includes('2.'), 'Multiple actions not displayed');
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#confirm-yes').disabled);
  ensure((await page.locator('#confirm-desc').textContent()).includes('2.'), 'Pending actions lost on refresh');
  await page.locator('#confirm-yes').click();
  await page.waitForFunction(() => document.querySelector('#chat').textContent.includes('已确认测试操作'));
  await ready();
  await send('再测试一次确认');
  await page.waitForFunction(() => !document.querySelector('#confirm-no').disabled);
  await page.locator('#confirm-no').click();
  await page.waitForFunction(() => document.querySelector('#chat').textContent.includes('已取消测试操作'));
  await ready();

  const slowId = await newConversation();
  const other = await page.context().newPage();
  try {
    await other.goto('http://127.0.0.1:18765/');
    await other.waitForFunction(() => !document.querySelector('#send').disabled);
    const started = page.waitForResponse(response => response.url().endsWith('/api/chat'));
    await send('慢请求');
    await started;
    const blocked = await other.evaluate(async id => {
      const response = await fetch('/api/chat', { method: 'POST', headers: {
        'Content-Type': 'application/json', Authorization: 'Bearer ' + localStorage.getItem('cc_token'),
      }, body: JSON.stringify({ conversation_id: id, message: '并发请求' }) });
      return response.status;
    }, slowId);
    ensure(blocked === 409, 'Concurrent turn was not rejected');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#conversation-status').textContent.includes('仍在处理'));
    const afterDisconnect = await other.evaluate(async id => {
      const response = await fetch('/api/chat', { method: 'POST', headers: {
        'Content-Type': 'application/json', Authorization: 'Bearer ' + localStorage.getItem('cc_token'),
      }, body: JSON.stringify({ conversation_id: id, message: '断连后的并发请求' }) });
      return response.status;
    }, slowId);
    ensure(afterDisconnect === 409, 'Disconnect released a still-running conversation');
    await page.waitForFunction(() => document.querySelector('#chat').textContent.includes('中文流式测试通过：慢请求'));
    await ready();
  } finally { await other.close(); }

  await newConversation();
  for (let i = 0; i < 6; i++) {
    await send('额度测试 ' + i);
    await page.waitForFunction(i => document.querySelector('#chat').textContent.includes('中文流式测试通过：额度测试 ' + i), i);
    if (i < 5) await ready();
  }
  await page.waitForFunction(() => document.querySelector('#conversation-status').textContent.includes('额度已用完'));
  ensure(await page.locator('#send').isDisabled(), 'Exhausted conversation can still send');
  await newConversation();
  await send('新会话可继续');
  await page.waitForFunction(() => document.querySelector('#chat').textContent.includes('中文流式测试通过：新会话可继续'));
  await ready();
  await page.setViewportSize({ width: 390, height: 844 });
  ensure(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Chat mobile overflow');
  ensure(await page.locator('#new-conversation').isVisible(), 'Mobile conversation controls missing');
  await page.setViewportSize({ width: 1440, height: 900 });

  // Exercise UTF-8 split at every byte, CRLF, and an unterminated final SSE frame.
  const parsed = await page.evaluate(async () => {
    const { streamChat } = await import('/assets/js/api.js');
    const original = window.fetch;
    const bytes = new TextEncoder().encode('data: {"type":"token","text":"字节拆分中文"}\r\n\r\ndata: {"type":"done"}');
    window.fetch = async () => new Response(new ReadableStream({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      },
    }));
    const events = [];
    try { await streamChat({ message: 'parser test' }, event => events.push(event)); }
    finally { window.fetch = original; }
    return events;
  });
  ensure(parsed.length === 2 && parsed[0].text === '字节拆分中文', 'SSE byte decoding failed');

  await page.locator('#logout').click();
  await page.locator('#login-mask.show').waitFor();
  ensure(await page.locator('.msg').count() === 0, 'Logout did not clear messages');
  await page.locator('#login-user').fill(username);
  await page.locator('#login-pass').fill('Testpass123');
  await page.locator('#login-pass').press('Enter');
  await page.locator('#login-mask.show').waitFor({ state: 'hidden' });
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#login-mask').classList.contains('show'));
  ensure(await page.locator('#who').textContent() === username, 'Stored session lost after reload');
  await page.route('**/api/me/courses?*', route => route.fulfill({ status: 401,
    contentType: 'application/json', body: '{"detail":"expired"}' }));
  await page.locator('#data-toggle').click();
  await page.locator('#login-mask.show').waitFor();
  ensure((await page.locator('#login-err').textContent()).includes('登录已过期'), '401 not handled');
  ensure(await page.evaluate(() => !localStorage.getItem('cc_token')), 'Expired token retained');
  await page.setViewportSize({ width: 390, height: 844 });
  ensure(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile overflow');
  await page.setViewportSize({ width: 1440, height: 900 });
  ensure(errors.length === 0, 'Browser errors: ' + errors.join('; '));
  return { passed: true, checks: ['registration', 'login/reload/logout', 'course/grade CRUD',
    'SSE UTF-8/CRLF', 'history/selection/reload', 'multi-action approve/reject', 'concurrency/disconnect recovery',
    'quota/new conversation', 'expired session', 'mobile layout'], browserErrors: errors };
}
