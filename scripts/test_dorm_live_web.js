// Restore the real-model result through Web + gateway, with fixture-only Dorm accounts.
async page => {
  const origin = 'http://127.0.0.1:18766';
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const ensure = (condition, message) => { if (!condition) throw new Error(message); };
  await page.setViewportSize({ width: 1280, height: 940 });
  await page.goto(origin + '/__fixture');
  await page.getByText('真实模型与知识检索已启用。', { exact: false }).waitFor();
  await page.getByRole('button', { name: '测试身份一', exact: true }).click();
  await page.locator('#agent-question:enabled').waitFor();
  // The login restores the last selected conversation, which can predate these rules.
  // Select the fresh real-model case created by eval_dorm_answers.py instead.
  const question = '出勤不足会怎样影响考试资格？只回答考试资格。';
  const token = await page.evaluate(() => localStorage.getItem('token'));
  const response = await page.request.get(origin + '/api/agent/conversations', { headers: { Authorization: 'Bearer ' + token } });
  const fresh = (await response.json()).data.conversations.find(item => item.title === question)?.id;
  ensure(fresh, 'Run eval_dorm_answers.py to prepare the fresh real-model case');
  await page.evaluate(id => sessionStorage.setItem('dorm:agent:1', id), fresh);
  await page.reload();
  await page.locator('.agent-message--user').filter({ hasText: question }).waitFor();
  await page.locator('#agent-question:enabled').waitFor();
  ensure(await page.locator('.agent-toolbar, .agent-conversation, .agent-page select').count() === 0, 'Conversation toolbar is still visible');
  ensure(await page.getByRole('button', { name: '新建', exact: true }).count() === 0, 'New button is still visible');
  ensure(await page.getByRole('button', { name: '刷新', exact: true }).count() === 0, 'Refresh button is still visible');
  const text = await page.locator('.agent-messages').innerText();
  ensure(text.trim().length > 0, 'Missing real answer');
  const citations = page.locator('.agent-message--assistant a');
  ensure(await citations.count() === 0, 'Unexpected source links');
  ensure(!/来源|生效日期|时效未核实|来自|整理快照/.test((await page.locator('.agent-message--assistant').allInnerTexts()).join('\n')), 'Unexpected source or date details');
  const conversation = await page.evaluate(() => sessionStorage.getItem('dorm:agent:1'));
  await page.reload();
  await page.locator('#agent-question:enabled').waitFor();
  ensure(await page.locator('.agent-messages').innerText() === text, 'Real history changed on reload');
  ensure(await page.evaluate(() => sessionStorage.getItem('dorm:agent:1')) === conversation, 'Conversation changed on reload');
  await page.locator('.agent-messages').evaluate(element => { element.scrollTop = 0; });
  await page.screenshot({ path: '.playwright-cli/dorm-agent-live-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#agent-question:enabled').waitFor();
  ensure(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Real Markdown overflows on mobile');
  await page.screenshot({ path: '.playwright-cli/dorm-agent-live-mobile.png', fullPage: true });
  ensure(errors.length === 0, 'Browser exception: ' + errors.join('; '));
  return { passed: true, citation_links: 0, restored_after_refresh: true, mobile_width: 390, page_errors: errors.length, additional_model_requests: 0 };
}
