// Missing-index regression: run only with an intentionally empty isolated guide index.
// The normal default index now contains real Wiki guides; do not run this against it.
async page => {
  const origin = 'http://127.0.0.1:18766';
  await page.goto(origin + '/__fixture');
  await page.getByRole('button', { name: '测试身份一', exact: true }).click();
  await page.locator('#agent-question:enabled').waitFor();
  const token = await page.evaluate(() => localStorage.getItem('token'));
  const response = await page.request.post(origin + '/api/agent/conversations', { headers: { Authorization: 'Bearer ' + token } });
  if (!response.ok()) throw new Error('Cannot prepare guide check conversation');
  const conversation = (await response.json()).data.id;
  await page.evaluate(id => sessionStorage.setItem('dorm:agent:1', id), conversation);
  await page.goto(origin + '/myzone/agent');
  await page.locator('#agent-question:enabled').waitFor();
  await page.locator('#agent-question').fill('住宿报到需要哪些材料？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.locator('.agent-message--assistant').waitFor();
  await page.locator('#agent-question:enabled').waitFor({ timeout: 90000 });
  const answer = await page.locator('.agent-message--assistant .agent-message-body').innerText();
  if (answer.length > 180 || !/无法|不能确认|暂无|没有|未接入|未导入/.test(answer)) throw new Error('Unimported guide state was not explained concisely');
  if (/来源|生效日期|时效未核实|我先|我查|collected_at|effective_date|来自/.test(answer)) throw new Error('Unexpected output details');
  if (await page.locator('.agent-toolbar, .agent-page select').count()) throw new Error('Toolbar returned');
  await page.reload();
  await page.locator('#agent-question:enabled').waitFor();
  if (await page.locator('.agent-message--assistant .agent-message-body').innerText() !== answer) throw new Error('Guide reply changed after reload');
  return { passed: true, real_web: true, missing_guides_handled: true, characters: answer.length, history_restored: true };
}
