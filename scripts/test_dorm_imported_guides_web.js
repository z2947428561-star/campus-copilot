// Test imported real Wiki content through actual Web + gateway + model.
async page => {
  const origin = 'http://127.0.0.1:18766';
  await page.goto(origin + '/__fixture');
  await page.getByRole('button', { name: '测试身份一', exact: true }).click();
  await page.locator('#agent-question:enabled').waitFor();
  const token = await page.evaluate(() => localStorage.getItem('token'));
  const response = await page.request.post(origin + '/api/agent/conversations', { headers: { Authorization: 'Bearer ' + token } });
  if (!response.ok()) throw new Error('Failed to prepare imported-guide check');
  const id = (await response.json()).data.id;
  await page.evaluate(id => sessionStorage.setItem('dorm:agent:1', id), id);
  await page.goto(origin + '/myzone/agent');
  await page.locator('#agent-question:enabled').waitFor();
  await page.locator('#agent-question').fill('AC系统里想查看以前学期的成绩，应该切换哪个选项？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.locator('.agent-message--assistant').waitFor();
  await page.locator('#agent-question:enabled').waitFor({ timeout: 90000 });
  const answer = await page.locator('.agent-message--assistant .agent-message-body').innerText();
  if (!/Academic\s*Session/i.test(answer) || !/选择|切换|调整/.test(answer)) throw new Error('Guide-backed answer is missing the recorded option');
  if (answer.length > 180 || /来源|生效日期|时效未核实|我先|我查|collected_at|effective_date|来自/.test(answer)) throw new Error('Unexpected answer format');
  await page.reload();
  await page.locator('#agent-question:enabled').waitFor();
  if (await page.locator('.agent-message--assistant .agent-message-body').innerText() !== answer) throw new Error('Imported-guide answer was not restored');
  return { passed: true, real_web: true, real_imported_guides: true, characters: answer.length, history_restored: true, conversation_id: id };
}
