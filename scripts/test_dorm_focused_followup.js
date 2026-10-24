// Run against the live local preview after updating the Dorm prompt.
async page => {
  await page.goto('http://127.0.0.1:18766/__fixture');
  await page.getByRole('button', { name: '测试身份一', exact: true }).click();
  await page.locator('#agent-question:enabled').waitFor();
  const token = await page.evaluate(() => localStorage.getItem('token'));
  const response = await page.request.get('http://127.0.0.1:18766/api/agent/conversations', { headers: { Authorization: 'Bearer ' + token } });
  const old = (await response.json()).data.conversations.filter(item => item.id !== 'main').at(-1)?.id;
  if (!old) throw new Error('Missing saved conversation');
  await page.evaluate(id => sessionStorage.setItem('dorm:agent:1', id), old);
  await page.reload();
  await page.locator('#agent-question:enabled').waitFor();
  await page.locator('#agent-question').fill('那出勤不够还能参加期末考试吗？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.locator('#agent-question:enabled').waitFor({ timeout: 90000 });
  const message = page.locator('.agent-message--assistant .agent-message-body').last();
  const text = await message.innerText();
  if (text.length > 220 || /重修|60%|SFS|collected_at|effective_date|manual_summary|我先|我查|来源|生效日期|时效未核实|来自|整理快照|根据.{0,30}(资料|手册|快照|知识库)/.test(text)) {
    throw new Error('Follow-up answer expanded beyond the question; readable characters=' + text.length);
  }
  if (await message.locator('a').count()) throw new Error('Unexpected source link');
  if (/带着来源|核对来源|适用日期/.test(await page.locator('.agent-page').innerText().then(text => text.split('对话记录')[0]))) throw new Error('Obsolete source copy');
  return { passed: true, real_web_followup: true, readable_characters: text.length, sources: await message.locator('a').count() };
}
