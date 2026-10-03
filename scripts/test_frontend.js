// Run against an isolated local app with playwright-cli run-code --filename=...
// Real auth/student APIs; mocked chat avoids model calls and private seed access.
async page => {
  await page.unrouteAll({ behavior: 'wait' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const ensure = (condition, message) => { if (!condition) throw new Error(message); };
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
  await page.locator('#login-user').fill('TST2601001');
  await page.locator('#register-submit').click();
  await page.locator('#login-mask.show').waitFor({ state: 'hidden' });
  ensure(await page.locator('#who').textContent() === 'TST2601001', 'Registration session missing');

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

  const blockedStatus = await page.evaluate(async () => {
    const response = await fetch('/api/chat', { method: 'POST', headers: {
      'Content-Type': 'application/json', Authorization: 'Bearer ' + localStorage.getItem('cc_token'),
    }, body: JSON.stringify({ message: 'must not call a model' }) });
    return response.status;
  });
  ensure(blockedStatus === 503, 'Test app must block real model calls');

  const resumes = [];
  let mode = 'normal';
  await page.route('**/api/chat', async route => {
    const request = route.request().postDataJSON();
    let events;
    if ('resume' in request) {
      resumes.push(request.resume);
      events = [{ type: 'token', text: request.resume ? '已确认测试操作' : '已取消测试操作' }, { type: 'done' }];
    } else if (mode === 'interrupt') {
      events = [{ type: 'interrupt', description: '测试确认', tool: 'calculate_gpa', args: {} }];
    } else {
      events = [{ type: 'token', text: '中文流式' }, { type: 'token', text: '测试通过' }, { type: 'done' }];
    }
    await route.fulfill({ contentType: 'text/event-stream', body: events.map(event =>
      'data: ' + JSON.stringify(event) + '\r\n\r\n').join('') });
  });
  await page.locator('#input').fill('测试消息');
  await page.locator('#input').press('Enter');
  await page.waitForFunction(() => document.querySelector('.msg.bot')?.textContent === '中文流式测试通过');
  mode = 'interrupt';
  await page.locator('[data-question]').first().click();
  await page.locator('#confirm-yes').waitFor({ state: 'visible' });
  await page.locator('#confirm-yes').click();
  await page.waitForFunction(() => document.querySelector('#chat').textContent.includes('已确认测试操作'));
  await page.locator('#input').fill('再测试一次确认');
  await page.locator('#send').click();
  await page.locator('#confirm-no').waitFor({ state: 'visible' });
  await page.locator('#confirm-no').click();
  await page.waitForFunction(() => document.querySelector('#chat').textContent.includes('已取消测试操作'));
  ensure(JSON.stringify(resumes) === '[true,false]', 'HITL resume payload changed');

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
  await page.locator('#login-pass').fill('Testpass123');
  await page.locator('#login-pass').press('Enter');
  await page.locator('#login-mask.show').waitFor({ state: 'hidden' });
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#login-mask').classList.contains('show'));
  ensure(await page.locator('#who').textContent() === 'TST2601001', 'Stored session lost after reload');
  await page.route('**/api/me/courses', route => route.fulfill({ status: 401,
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
    'SSE UTF-8/CRLF', 'approve/reject', 'expired session', 'mobile layout'], browserErrors: errors };
}
