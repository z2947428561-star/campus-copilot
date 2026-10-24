// Run only against scripts/run_dorm_web_test.py (temporary accounts / fake model).
async page => {
  await page.unrouteAll({ behavior: 'wait' });
  const origin = 'http://127.0.0.1:18766';
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const ensure = (condition, message) => { if (!condition) throw new Error(message); };
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(origin + '/myzone/agent');
  await page.evaluate(() => {
    localStorage.clear(); sessionStorage.clear();
    localStorage.setItem('dorm-install-hint-dismissed', 'true');
    sessionStorage.setItem('skipLogin', '1');
  });
  await page.goto(origin + '/myzone/agent');
  await page.locator('.agent-gate').waitFor();
  ensure(await page.locator('.agent-gate a').textContent() === '去登录', 'Guest must sign in');

  async function login(id) {
    const response = await page.request.post(origin + '/__fixture/login', { data: { id } });
    const account = await response.json();
    await page.evaluate(({ token, user }) => {
      localStorage.setItem('token', token); localStorage.setItem('user', JSON.stringify(user));
    }, account);
    await page.goto(origin + '/myzone/agent');
    await page.locator('#agent-question:enabled').waitFor();
    return account;
  }
  const first = await login(1);
  async function currentId() {
    const saved = await page.evaluate(() => sessionStorage.getItem('dorm:agent:1'));
    if (saved) return saved;
    const response = await page.request.get(origin + '/api/agent/conversations', { headers: { Authorization: 'Bearer ' + first.token } });
    return (await response.json()).data.conversations[0].id;
  }
  async function activate(id) {
    await page.evaluate(id => sessionStorage.setItem('dorm:agent:1', id), id);
    await page.reload();
    await page.locator('#agent-question:enabled').waitFor();
  }
  async function prepareConversation() {
    const response = await page.request.post(origin + '/api/agent/conversations', { headers: { Authorization: 'Bearer ' + first.token } });
    const item = (await response.json()).data;
    await activate(item.id);
    return item.id;
  }
  ensure(await page.locator('.agent-toolbar, .agent-conversation, .agent-page select').count() === 0, 'Toolbar must be removed');
  await page.screenshot({ path: '.playwright-cli/dorm-agent-desktop.png', fullPage: true });
  await page.locator('#agent-question').fill('政策查询测试');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByText('中文流式测试通过：政策查询测试', { exact: true }).waitFor();
  await page.locator('#agent-question:enabled').waitFor();
  const firstId = await currentId();
  await prepareConversation();
  await page.locator('#agent-question:enabled').waitFor();
  await page.locator('#agent-question').fill('独立会话历史');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByText('中文流式测试通过：独立会话历史', { exact: true }).waitFor();
  const secondId = await currentId();
  ensure(secondId !== firstId, 'New conversation must have a different id');
  await page.reload();
  await page.getByText('中文流式测试通过：独立会话历史', { exact: true }).waitFor();
  const second = await login(2);
  ensure(!await page.getByText('独立会话历史', { exact: true }).count(), 'Different user saw previous history');
  const denied = await page.request.get(origin + '/api/agent/conversations/' + secondId, {
    headers: { Authorization: 'Bearer ' + second.token },
  });
  ensure(denied.status() === 404, 'Cross-account history must be denied');

  await page.evaluate(({ token, user }) => {
    localStorage.setItem('token', token); localStorage.setItem('user', JSON.stringify(user));
  }, first);
  await page.goto(origin + '/myzone/agent');
  await page.locator('#agent-question:enabled').waitFor();
  await activate(firstId);
  await page.locator('#agent-question:enabled').waitFor();
  await page.locator('#agent-question').fill('双重确认 GPA');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByRole('button', { name: '取消操作', exact: true }).waitFor();
  await page.getByRole('button', { name: '取消操作', exact: true }).click();
  await page.getByText('已取消测试操作', { exact: true }).waitFor();
  await page.locator('#agent-question:enabled').waitFor();

  await prepareConversation();
  await page.locator('#agent-question:enabled').waitFor();
  let slowPosts = 0;
  page.on('request', req => { if (req.method() === 'POST' && req.url().endsWith('/api/agent/chat') && req.postData()?.includes('慢请求测试')) slowPosts++; });
  await page.locator('#agent-question').fill('慢请求测试');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByRole('button', { name: '稍后查看', exact: true }).click();
  await page.getByText('中文流式测试通过：慢请求测试', { exact: true }).waitFor({ timeout: 15000 });
  ensure(slowPosts === 1, 'Interrupted turn was automatically resent');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.agent-page').waitFor();
  ensure(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile page overflows horizontally');
  await page.screenshot({ path: '.playwright-cli/dorm-agent-mobile.png', fullPage: true });
  await page.request.post(origin + '/__fixture/availability', { data: { available: false } });
  await page.reload();
  await page.getByRole('alert').filter({ hasText: '校园助手尚未配置' }).waitFor();
  await page.request.post(origin + '/__fixture/availability', { data: { available: true } });
  ensure(errors.length === 0, 'Browser exceptions: ' + errors.join('; '));
  console.log('PASS: guest, SSE, new/switch/restore, account isolation, approvals, disconnect recovery, mobile layout, unavailable service; no browser exceptions.');
}
