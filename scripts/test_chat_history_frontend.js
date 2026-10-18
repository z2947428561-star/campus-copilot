// Run against run_frontend_test_app.py --summarize on port 18765.
async page => {
  await page.unrouteAll({ behavior: 'wait' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const ensure = (value, message) => { if (!value) throw new Error(message); };
  const ready = () => page.waitForFunction(() => !document.querySelector('#send').disabled);
  await page.goto('http://127.0.0.1:18765/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  const username = 'HST2610' + String(Math.floor(Math.random() * 1000)).padStart(3, '0');
  await page.locator('#login-user').fill(username);
  await page.locator('#login-pass').fill('Testpass123');
  await page.locator('#register-submit').click();
  await ready();
  await page.locator('#new-conversation').click();
  await ready();
  const cid = await page.locator('#conversation-select').inputValue();
  for (let index = 0; index < 4; index++) {
    await page.locator('#input').fill('保留原文-' + index);
    await page.locator('#send').click();
    await page.waitForFunction(index => document.querySelector('#chat').textContent.includes('中文流式测试通过：保留原文-' + index), index);
    await ready();
  }
  const verify = async () => {
    const messages = await page.locator('#chat .msg').allTextContents();
    const expected = [];
    for (let index = 0; index < 4; index++) expected.push('保留原文-' + index, '中文流式测试通过：保留原文-' + index);
    ensure(JSON.stringify(messages) === JSON.stringify(expected), 'History text, roles or order changed');
    ensure(!messages.some(text => text.includes('synthetic-summary') || text.includes('Here is a summary')), 'Internal summary displayed as a chat message');
  };
  await verify();
  await page.reload();
  await ready();
  await verify();
  await page.locator('#new-conversation').click();
  await page.waitForFunction(cid => document.querySelector('#conversation-select').value !== cid, cid);
  await ready();
  await page.locator('#conversation-select').selectOption(cid);
  await ready();
  await verify();
  ensure(errors.length === 0, errors.join('\n'));
  return { passed: true, checks: ['摘要后原文与顺序', '刷新恢复', '切换恢复', '无摘要混入或重复', '无脚本异常'] };
}
