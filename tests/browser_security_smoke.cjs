/* Security/integrity UI regressions. Only disposable SQLite and fictitious data. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'compac-security-ui-'));
const base = 'http://127.0.0.1:' + (process.env.COMPAC_SECURITY_TEST_PORT || '8825');
const child = spawn(path.join(root, '.venv/bin/python'), ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', new URL(base).port], {
  cwd: root, env: {...process.env, DATABASE_URL: '', COMPAC_REQUIRE_POSTGRES: '', COMPAC_DB: path.join(temp, 'test.db'), RENDER: '', COMPAC_SETUP_TOKEN: '', COMPAC_COOKIE_SECURE: '0', COMPAC_PUBLIC_URL: base, RENDER_EXTERNAL_URL: ''}, stdio: 'ignore',
});
let browser;
(async () => { try {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(base + '/health')).ok) break; } catch {}
    if (i === 99) throw Error('Disposable server did not start');
    await new Promise(r => setTimeout(r, 100));
  }
  browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
  const ctx = await browser.newContext({viewport: {width: 1440, height: 1000}, timezoneId: 'America/Sao_Paulo'});
  const page = await ctx.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base); await page.locator('#auth-screen').waitFor({state: 'visible'});
  const contrast = await page.evaluate(() => {
    const linear = v => (v /= 255) <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4);
    return ['#auth-description', '#auth-help', '.auth-security'].map(sel => {
      const rgb = getComputedStyle(document.querySelector(sel)).color.match(/[\d.]+/g).slice(0, 3).map(Number).map(linear);
      return 1.05 / (rgb.reduce((sum, value, i) => sum + value * [.2126, .7152, .0722][i], 0) + .05);
    });
  });
  contrast.forEach(ratio => assert.ok(ratio >= 4.5, 'Small login text needs 4.5:1 contrast'));
  const initialPassword = 'Security-Test-2026!';
  await page.locator('#auth-name').fill('Auditoria Fictícia');
  await page.locator('#auth-username').fill('audit'); await page.locator('#auth-password').fill(initialPassword);
  await page.locator('#auth-submit').click(); await page.locator('#app-shell').waitFor({state: 'visible'});
  await page.getByRole('heading', {name: 'Visão geral', exact: true}).waitFor();
  assert.equal(await page.locator('.quick-grid').evaluate(grid => { const panel = grid.closest('.panel').getBoundingClientRect(); return [...grid.children].some(el => el.getBoundingClientRect().right > panel.right); }), false, 'Dashboard actions must fit their panel');
  const headers = {'X-Compac-Client': 'web', Origin: base};
  async function create(entity, data) { const response = await ctx.request.post(base + '/api/catalog/' + entity, {headers, data}); assert.equal(response.status(), 201, await response.text()); return (await response.json()).id; }
  async function route(hash, heading) { await page.goto(base + '/#' + hash); await page.getByRole('heading', {name: heading, exact: true}).waitFor(); }
  const category = await create('categories', {name: 'Categoria anterior', description: ''});
  const location = await create('locations', {name: 'Local fictício', work_id: null});
  const material = await create('materials', {code: 'SEC001', description: 'Material fictício', category_id: category, unit: 'UN', minimum_stock: 0, individualizable: false, status: 'ATIVO'});
  await route('cadastros/materials', 'Materiais'); await page.getByRole('cell', {name: 'Categoria anterior', exact: true}).waitFor();
  assert.equal((await ctx.request.put(base + '/api/catalog/categories/' + category, {headers, data: {name: 'Categoria atualizada', description: ''}})).status(), 200);
  await page.locator('#refresh-button').click(); await page.getByRole('cell', {name: 'Categoria atualizada', exact: true}).waitFor();
  await page.locator('[data-action=new-catalog]').first().click();
  assert.equal(await page.getByRole('dialog', {name: 'Cadastrar material', exact: true}).isVisible(), true);
  await page.locator('[data-dialog-close]').first().click();
  await page.clock.setFixedTime(new Date('2026-11-05T01:30:00Z'));
  await route('despesas', 'Despesas'); await page.locator('[data-action=new-catalog]').first().click();
  assert.equal(await page.locator('[name=purchase_date]').inputValue(), '2026-11-04');
  await page.locator('[data-dialog-close]').first().click();
  await page.setViewportSize({width: 390, height: 844}); await page.locator('#menu-toggle').click();
  assert.equal(await page.evaluate(() => document.activeElement.id), 'sidebar-close');
  assert.equal(await page.locator('.app-workspace').evaluate(el => el.inert), true);
  for (let i = 0; i < 25; i++) { await page.keyboard.press('Tab'); assert.equal(await page.evaluate(() => !!document.activeElement.closest('#sidebar')), true); }
  await page.keyboard.press('Escape'); assert.equal(await page.evaluate(() => document.activeElement.id), 'menu-toggle');
  assert.equal(await page.locator('.app-workspace').evaluate(el => el.inert), false);
  await page.setViewportSize({width: 1440, height: 1000});
  await route('movimentacoes', 'Movimentações');
  const keys = []; let loseNext = true;
  await page.route('**/api/movements', async intercepted => {
    if (intercepted.request().method() !== 'POST') return intercepted.continue();
    const key = intercepted.request().headers()['idempotency-key'];
    assert.match(key, /^[0-9a-f-]{36}$/i); keys.push(key);
    if (loseNext) { loseNext = false; const response = await intercepted.fetch(); assert.equal(response.status(), 201, await response.text()); await intercepted.abort('failed'); }
    else { await new Promise(r => setTimeout(r, 100)); await intercepted.continue(); }
  });
  async function newEntry(quantity) {
    await page.locator('[data-action=new-movement]').first().click();
    await page.locator('[name=material_id]').selectOption(String(material));
    await page.locator('[name=quantity]').fill(String(quantity)); await page.locator('[name=destination_id]').selectOption(String(location));
  }
  const modal = page.locator('#form-dialog');
  await newEntry(5); await page.locator('#modal-submit').click(); await page.locator('#modal-error').waitFor({state: 'visible'});
  assert.equal((await (await ctx.request.get(base + '/api/movements')).json()).length, 1, 'Lost response still committed once');
  await page.locator('#modal-submit').click(); await modal.waitFor({state: 'hidden'});
  assert.equal(keys[0], keys[1], 'Unchanged retry must reuse the original intent');
  assert.equal((await (await ctx.request.get(base + '/api/movements')).json()).length, 1, 'Replay must not add a movement');
  loseNext = true;
  await newEntry(1); await page.locator('#modal-submit').click(); await page.locator('#modal-error').waitFor({state: 'visible'});
  await page.locator('[name=quantity]').fill('3'); await page.locator('#modal-submit').click(); await modal.waitFor({state: 'hidden'});
  assert.notEqual(keys[1], keys[2], 'New modal must get a new intent');
  assert.notEqual(keys[2], keys[3], 'Changed payload after failure must get a new intent');
  await newEntry(2);
  await page.locator('#modal-form').evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
  await modal.waitFor({state: 'hidden'});
  assert.equal(keys.length, 5, 'Pending guard must reject repeated programmatic submissions');
  const movements = await (await ctx.request.get(base + '/api/movements')).json();
  assert.equal(movements.length, 4);
  const stock = await (await ctx.request.get(base + '/api/stock')).json();
  assert.equal(stock.find(row => row.material_id === material && row.location_id === location).quantity, 11);
  await page.locator('[data-action=change-password]').click();
  await page.locator('[name=current_password]').fill('Incorrect-Password!');
  await page.locator('[name=new_password]').fill('Updated-Security-2026!');
  await page.locator('[name=confirm_password]').fill('Updated-Security-2026!');
  await page.locator('#modal-submit').click(); await page.locator('#modal-error').waitFor({state: 'visible'});
  assert.equal(await modal.isVisible(), true, 'Incorrect current password must preserve the form/session');
  await page.locator('[name=current_password]').fill(initialPassword); await page.locator('#modal-submit').click();
  await modal.waitFor({state: 'hidden'}); await page.locator('#auth-screen').waitFor({state: 'visible'});
  assert.equal((await ctx.request.get(base + '/api/auth/me')).status(), 401, 'Password change revokes current session');
  await page.locator('#auth-username').fill('audit'); await page.locator('#auth-password').fill('Updated-Security-2026!');
  await page.locator('#auth-submit').click(); await page.locator('#app-shell').waitFor({state: 'visible'});
  assert.deepEqual(errors, []);
  console.log('PASS: movement lost-response replay, changed-payload/new-modal intents, pending guard, stock=11 after 4 committed operations; cache refresh, local date, dialog name, login contrast, mobile focus, clipping, own-password change/relogin.');
} finally {
  if (browser) await browser.close();
  if (child.exitCode === null) { const stopped = new Promise(r => child.once('exit', r)); child.kill(); await stopped; }
  fs.rmSync(temp, {recursive: true, force: true});
}})().catch(error => { console.error(error); process.exit(1); });
