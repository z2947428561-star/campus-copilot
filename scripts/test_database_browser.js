// Run with playwright-cli against scripts/run_frontend_test_app.py on port 18765.
async page => {
  await page.unrouteAll({ behavior: 'wait' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const ensure = (ok, message) => { if (!ok) throw new Error(message); };
  const results = [];
  const username = 'DBV2610' + String(Math.floor(Math.random() * 1000)).padStart(3, '0');
  const root = 'http://127.0.0.1:18765';
  const ready = () => page.waitForFunction(() => document.querySelector('#db-status').textContent.startsWith('已读取'));
  const choose = async (source, table) => {
    await page.locator(`[data-source="${source}"][data-table="${table}"]`).click();
    await ready();
  };

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(root + '/database');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.locator('#db-gate').waitFor({ state: 'visible' });
  ensure(await page.locator('#db-app').isHidden(), 'Data visible before login');
  results.push('未登录引导');

  await page.goto(root + '/');
  await page.locator('#login-user').fill(username);
  await page.locator('#login-pass').fill('Testpass123');
  await page.locator('#register-submit').click();
  await page.locator('#login-mask.show').waitFor({ state: 'hidden' });
  await page.getByRole('link', { name: '数据浏览器', exact: true }).click();
  await ready();
  ensure(await page.locator('#db-table tbody tr').count() === 20, 'Public course count');
  ensure(await page.locator('#db-user').textContent() === username, 'Current account missing');
  results.push('入口、目录与真实公共数据');

  await page.locator('#db-query').fill('zzzz-no-record');
  await page.getByRole('button', { name: '搜索', exact: true }).click();
  await ready();
  ensure(await page.locator('#db-empty').isVisible(), 'Empty search state missing');
  await page.locator('#db-clear').click();
  await ready();
  await page.locator('#db-page-size').selectOption('10');
  await ready();
  ensure(await page.locator('#db-table tbody tr').count() === 10, 'Page size ignored');
  await page.locator('#db-next').click();
  await ready();
  ensure((await page.locator('#db-page').textContent()).includes('2'), 'Next page failed');
  await page.getByRole('button', { name: '按课程代码排序', exact: true }).click();
  await ready();
  ensure((await page.locator('#db-page').textContent()).includes('1'), 'Sort did not reset page');
  ensure(await page.locator('th[aria-sort="ascending"]').count() === 1, 'Sort accessibility state missing');
  await page.getByRole('button', { name: '查看记录 1', exact: true }).click();
  await page.locator('#db-detail[open]').waitFor();
  ensure((await page.locator('#db-detail-fields').textContent()).includes('course_id'), 'Detail fields missing');
  await page.keyboard.press('Escape');
  ensure(await page.locator('#db-detail').isHidden(), 'Escape failed to close record');
  results.push('搜索、空状态、分页、排序与详情');

  await page.getByRole('button', { name: '字段结构', exact: true }).click();
  ensure(await page.locator('#db-schema-rows tr').count() === 7, 'Column schema missing');
  await page.getByRole('button', { name: '表间关系', exact: true }).click();
  ensure(await page.locator('.db-relation').count() === 3, 'Physical and logical relations missing');
  await page.locator('.db-relation button').filter({ hasText: 'campus.timetable' }).click();
  await ready();
  ensure(await page.locator('#db-title').textContent() === '排课', 'Relation jump failed');
  await page.getByRole('button', { name: '数据记录', exact: true }).click();
  results.push('字段结构与关联跳转');

  await choose('documents', 'snapshots');
  ensure((await page.locator('#db-count').textContent()).includes('16 条记录'), 'Snapshot count missing');
  await page.getByRole('button', { name: '查看记录 1', exact: true }).click();
  ensure((await page.locator('#db-detail-fields').textContent()).includes('manual_summary'), 'Snapshot provenance missing');
  await page.locator('#db-detail-close').click();
  await page.locator('[data-source="index"]').click();
  await page.locator('#db-error').waitFor({ state: 'visible' });
  ensure((await page.locator('#db-error-message').textContent()).includes('Chroma'), 'Unavailable index guidance missing');
  await page.locator('#db-retry').click();
  await page.locator('#db-error').waitFor({ state: 'visible' });
  results.push('快照来源与索引故障恢复入口');

  const malicious = '<img src=x onerror="window.dbInjected=true">';
  await page.route('**/api/database/index/chunks?*', route => route.fulfill({ json: {
    source: 'index', table: 'chunks', label: '已入库分块', page: 1, page_size: 10, total: 1, has_more: false, sortable: false,
    columns: [{ name: 'id', label: '记录 ID', type: 'ID', primary: true }, { name: 'text', label: '分块正文', type: 'TEXT', primary: false }],
    rows: [{ id: 3, text: malicious }], info: { backend: '测试索引', collection: 'isolated_test', dimension: 1024 },
  } }));
  await page.locator('#db-retry').click();
  await ready();
  ensure((await page.locator('#db-table tbody').textContent()).includes(malicious), 'Index row missing');
  ensure(await page.locator('#db-table img').count() === 0, 'Table interpreted stored text as HTML');
  await page.getByRole('button', { name: '查看记录 1', exact: true }).click();
  ensure(await page.locator('#db-detail img').count() === 0, 'Detail interpreted stored text as HTML');
  ensure(!await page.evaluate(() => window.dbInjected), 'Stored content executed');
  await page.locator('#db-detail-close').click();
  await page.unroute('**/api/database/index/chunks?*');
  results.push('索引成功展示与文本注入防护（索引响应替身）');

  await page.evaluate(async () => {
    const result = await fetch('/api/me/grades', { method: 'PUT', headers: {
      'Content-Type': 'application/json', Authorization: 'Bearer ' + localStorage.getItem('cc_token'),
    }, body: JSON.stringify({ course_id: 'CS101', grade_point: 3.7, letter: 'A-' }) });
    if (!result.ok) throw new Error('Could not seed own grade');
  });
  await choose('personal', 'student_grades');
  ensure((await page.locator('#db-table tbody').textContent()).includes('3.7'), 'Own grade not visible');
  await page.getByRole('button', { name: '查看记录 1', exact: true }).click();
  const second = await page.context().newPage();
  await second.goto(root + '/');
  const bob = 'DBW2610' + String(Math.floor(Math.random() * 1000)).padStart(3, '0');
  await second.evaluate(async username => {
    const response = await fetch('/api/register', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password: 'Testpass123' }) });
    if (!response.ok) throw new Error('Second account registration failed');
    const session = await response.json();
    localStorage.setItem('cc_token', session.token);
    localStorage.setItem('cc_user', session.user_id);
  }, bob);
  await page.waitForFunction(bob => document.querySelector('#db-user').textContent === bob, bob);
  await ready();
  ensure(await page.locator('#db-detail').isHidden(), 'Account switch retained private detail');
  await choose('personal', 'student_grades');
  ensure(await page.locator('#db-empty').isVisible(), 'Second account saw the first account grade');
  ensure(!(await page.locator('#db-detail-fields').textContent()).includes('3.7'), 'Old private record retained');
  await second.close();
  results.push('个人记录与跨标签页账号切换隔离');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#db-directory summary').click();
  await choose('campus', 'courses');
  ensure(!await page.locator('#db-directory').evaluate(el => el.open), 'Mobile directory did not collapse');
  ensure(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'Mobile page overflow');
  await page.getByRole('button', { name: '查看记录 1', exact: true }).click();
  ensure(await page.locator('#db-detail').isVisible(), 'Mobile record unavailable');
  await page.locator('#db-detail-close').click();
  await page.screenshot({ path: '.playwright-cli/database-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  ensure(await page.locator('#db-directory').evaluate(el => el.open), 'Desktop directory not restored');
  await page.screenshot({ path: '.playwright-cli/database-desktop.png', fullPage: true });
  results.push('手机布局与桌面目录恢复');

  await page.evaluate(() => localStorage.setItem('cc_token', 'expired-token'));
  await page.reload();
  await page.locator('#db-gate').waitFor({ state: 'visible' });
  ensure(await page.locator('#db-table tbody tr').count() === 0, 'Expired session retained data');
  ensure(errors.length === 0, errors.join('\n'));
  results.push('登录过期清理与页面无脚本异常');
  return { passed: results.length, checks: results, errors };
}
