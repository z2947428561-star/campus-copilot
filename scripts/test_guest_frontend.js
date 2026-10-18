// Browser-only guest preview; authenticated APIs remain protected.
async page => {
  await page.unrouteAll({ behavior: 'wait' });
  const errors = [], apiCalls = [], checks = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.url().includes('/api/')) apiCalls.push(request.url()); });
  const ensure = (condition, message) => { if (!condition) throw new Error(message); };
  const gate = () => page.locator('#login-mask.show').waitFor();
  const skip = async () => {
    await page.locator('#login-skip').click();
    await page.locator('#login-mask.show').waitFor({ state: 'hidden' });
    ensure(await page.locator('#who').textContent() === '访客', 'Guest identity missing');
  };
  await page.goto('http://127.0.0.1:18765/');
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.reload();
  await gate();
  await page.locator('#login-pass').fill('Unsentpass123');
  apiCalls.length = 0;
  await skip();
  ensure(await page.locator('#login-pass').inputValue() === '', 'Guest preview retained an unsent password');
  ensure(await page.locator('#welcome').isVisible(), 'Guest welcome hidden');
  ensure(await page.locator('#new-conversation').isDisabled(), 'Guest can create a conversation');
  ensure(await page.locator('#semester-select').isDisabled(), 'Guest selector is active');
  ensure(!await page.evaluate(() => localStorage.getItem('cc_token')), 'Guest got a token');
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#who').textContent === '访客');
  ensure(await page.locator('#login-mask.show').count() === 0, 'Guest refresh reopened login');
  ensure(apiCalls.length === 0, 'Guest preview requested authenticated APIs');
  checks.push('暂不登录进入首页，刷新保留访客且不调用受保护 API');

  await page.locator('#send').click();
  await gate();
  ensure((await page.locator('#login-err').textContent()).includes('对话'), 'Chat login guidance missing');
  await skip();
  await page.locator('#data-toggle').click();
  await gate();
  ensure(await page.locator('#data-panel').getAttribute('aria-hidden') === 'true', 'Guest saw personal data');
  await skip();
  await page.locator('#database-link').click();
  await gate();
  ensure(page.url().endsWith('/'), 'Guest navigated into protected browser');
  ensure(apiCalls.length === 0, 'Guest action reached an authenticated API');
  checks.push('提问、个人数据与数据库入口提示登录');

  await skip();
  await page.locator('#logout').click();
  await gate();
  const username = 'GST2610' + String(Math.floor(Math.random() * 1000)).padStart(3, '0');
  await page.locator('#login-user').fill(username);
  await page.locator('#login-pass').fill('Testpass123');
  let releaseRegistration, registrationStarted;
  const holdRegistration = new Promise(resolve => { releaseRegistration = resolve; });
  const registrationRequest = new Promise(resolve => { registrationStarted = resolve; });
  await page.route('**/api/register', async route => {
    registrationStarted();
    await holdRegistration;
    await route.continue();
  });
  await page.locator('#register-submit').click();
  await registrationRequest;
  await page.waitForFunction(() => document.querySelector('#login-skip').disabled);
  ensure(await page.locator('#login-skip').isDisabled(), 'Skip can race an in-flight login');
  releaseRegistration();
  await page.waitForFunction(() => !document.querySelector('#send').disabled && document.querySelector('#who').textContent !== '访客');
  await page.unroute('**/api/register');
  ensure(await page.locator('#logout').textContent() === '退出', 'Authenticated account actions not restored');
  ensure(!await page.evaluate(() => sessionStorage.getItem('cc_guest')), 'Guest flag survived login');
  await page.locator('#logout').click();
  await gate();
  await page.reload();
  await gate();
  checks.push('访客登录、请求中禁用跳过、退出后恢复登录界面');

  await page.setViewportSize({ width: 390, height: 667 });
  await page.locator('#login-skip').scrollIntoViewIfNeeded();
  ensure(await page.locator('#login-skip').isVisible(), 'Mobile guest option inaccessible');
  await page.screenshot({ path: '.playwright-cli/guest-login-mobile.png', fullPage: true });
  await skip();
  ensure(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile guest layout overflow');
  checks.push('手机端跳过入口可访问，首页无横向溢出');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('#logout').click();
  await gate();
  await page.screenshot({ path: '.playwright-cli/guest-login-desktop.png', fullPage: true });
  ensure(errors.length === 0, errors.join('\n'));
  return { passed: true, checks, errors };
}
