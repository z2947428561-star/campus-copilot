// Real HTTP, temporary two-semester catalog, offline fake model.
async page => {
  await page.unrouteAll({ behavior: 'wait' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const ensure = (ok, message) => { if (!ok) throw new Error(message); };
  const username = 'SEM2610' + String(Math.floor(Math.random() * 1000)).padStart(3, '0');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('http://127.0.0.1:18765/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.locator('#login-user').fill(username);
  await page.locator('#login-pass').fill('Testpass123');
  await page.locator('#register-submit').click();
  await page.locator('#login-mask.show').waitFor({ state: 'hidden' });
  const ready = () => page.waitForFunction(() => !document.querySelector('#semester-select').disabled && !document.querySelector('#send').disabled);
  await ready();
  ensure(await page.locator('#semester-select option').count() === 2, 'Recorded semester selector missing');
  await page.locator('#semester-select').selectOption('2026-09');
  await page.locator('#data-toggle').click();
  await page.locator('#grade-course').fill('CS101');
  await page.locator('#grade-point').fill('3.7');
  await page.locator('#grade-letter').fill('A-');
  await page.locator('#save-grade').click();
  await page.waitForFunction(() => document.querySelector('#data-list').textContent.includes('3.7'));
  await page.locator('#semester-select').selectOption('2027-04');
  await page.waitForFunction(() => document.querySelector('#data-list').textContent.includes('暂无') && !document.querySelector('#data-list').textContent.includes('3.7'));
  await page.locator('#grade-point').fill('1');
  await page.locator('#grade-letter').fill('D');
  await page.locator('#save-grade').click();
  await page.waitForFunction(() => document.querySelector('#data-list').textContent.includes('D (1)'));
  await page.locator('#semester-select').selectOption('2026-09');
  await page.waitForFunction(() => document.querySelector('#data-list').textContent.includes('3.7'));

  // Return the older request after the new selection has already rendered.
  await page.locator('#semester-select').selectOption('2027-04');
  await page.waitForFunction(() => document.querySelector('#data-list').textContent.includes('D (1)'));
  let release, started, complete;
  const entered = new Promise(resolve => { started = resolve; });
  const completed = new Promise(resolve => { complete = resolve; });
  await page.route('**/api/me/grades?semester_id=2026-09', async route => {
    started();
    await new Promise(resolve => { release = resolve; });
    try { const response = await route.fetch(); await route.fulfill({ response }); } catch { /* Aborted on selection change. */ }
    complete();
  });
  await page.locator('#semester-select').selectOption('2026-09');
  await entered;
  await page.locator('#semester-select').selectOption('2027-04');
  await page.waitForFunction(() => document.querySelector('#data-list').textContent.includes('D (1)'));
  release();
  await completed;
  ensure(!(await page.locator('#data-list').textContent()).includes('3.7'), 'Late response restored old-semester records');
  await page.unroute('**/api/me/grades?semester_id=2026-09');

  await page.locator('#semester-select').selectOption('2026-09');
  await page.locator('#data-toggle').click();
  await page.locator('#input').fill('确认 GPA');
  await page.locator('#send').click();
  await page.locator('#confirm-bar').waitFor({ state: 'visible' });
  ensure(await page.locator('#semester-select').isDisabled(), 'Pending operation can change semester');
  await page.evaluate(username => sessionStorage.setItem('cc_semester:' + username, '2027-04'), username);
  await page.reload();
  await page.locator('#confirm-bar').waitFor({ state: 'visible' });
  ensure(await page.locator('#semester-select').inputValue() === '2026-09', 'Pending semester not restored');
  ensure(await page.locator('#semester-select').isDisabled(), 'Restored pending semester editable');
  await page.locator('#confirm-no').click();
  await ready();
  await page.locator('#semester-select').selectOption('2027-04');
  await page.reload();
  await ready();
  ensure(await page.locator('#semester-select').inputValue() === '2027-04', 'Selection lost on refresh');
  await page.setViewportSize({ width: 390, height: 844 });
  ensure(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Semester selector causes mobile overflow');
  ensure(await page.locator('#semester-select').isVisible(), 'Mobile semester selector missing');
  ensure((await page.locator('#semester-select').boundingBox()).width > 180, 'Mobile semester selection unreadable');
  ensure((await page.locator('#conversation-select').boundingBox()).width > 80, 'Mobile conversation selection collapsed');
  ensure(errors.length === 0, errors.join('\n'));
  return { passed: true, checks: ['cross-semester grades', 'late-response isolation', 'HITL semester lock',
    'HITL refresh restoration', 'selection persistence', 'mobile layout'], errors };
}
