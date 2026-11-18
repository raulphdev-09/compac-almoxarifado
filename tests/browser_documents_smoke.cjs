const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'compac-documents-'));
const output = process.env.COMPAC_TEST_ARTIFACTS || path.join('/tmp', 'compac-documents-artifacts');
const port = process.env.COMPAC_TEST_PORT || '8813';
const base = 'http://127.0.0.1:' + port;
fs.mkdirSync(output, { recursive: true });
// This smoke always owns a disposable SQLite database, even in a production shell.
const child = spawn(path.join(root, '.venv/bin/python'), ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port], {
  cwd: root,
  env: { ...process.env, COMPAC_DB: path.join(temp, 'test.db'), DATABASE_URL: '', COMPAC_REQUIRE_POSTGRES: '', RENDER: '', COMPAC_SETUP_TOKEN: '', COMPAC_COOKIE_SECURE: '0', COMPAC_PUBLIC_URL: '', RENDER_EXTERNAL_URL: '' },
  stdio: ['ignore', 'ignore', 'pipe'],
});
let browser, page, logs = '';
child.stderr.on('data', data => { logs = (logs + data.toString()).slice(-10000); });

(async () => {
  try {
    for (let i = 0; i < 160; i++) {
      if (child.exitCode !== null) throw Error('Servidor encerrou: ' + logs);
      try { if ((await fetch(base + '/health')).ok) break; } catch {}
      if (i === 159) throw Error('Servidor indisponível: ' + logs);
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', acceptDownloads: true });
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    async function get(endpoint) { const response = await context.request.get(base + '/api/' + endpoint); assert.equal(response.status(), 200, await response.text()); return response.json(); }
    async function create(entity, data) { const response = await context.request.post(base + '/api/catalog/' + entity, { headers: { 'X-Compac-Client': 'web' }, data }); assert.equal(response.status(), 201, await response.text()); return response.json(); }
    async function snapshot() { return Promise.all(['catalog/materials', 'stock', 'movements', 'loans', 'audit'].map(get)); }
    async function route(key, title) { await page.goto(base + '/#' + key); await page.getByRole('heading', { name: title, exact: true }).waitFor(); }
    const modal = page.locator('#form-dialog');
    async function fill(name, value) { const input = modal.locator('[name="' + name + '"]'); if (await input.evaluate(node => node.tagName) === 'SELECT') await input.selectOption(String(value)); else await input.fill(String(value)); }
    async function save() { await modal.locator('button[type=submit]').click(); await modal.waitFor({ state: 'hidden' }); }

    await page.goto(base);
    await page.locator('#auth-screen').waitFor({ state: 'visible' });
    await page.locator('#auth-name').fill('Equipe documentos');
    await page.locator('#auth-username').fill('admin');
    await page.locator('#auth-password').fill('BrowserTest123!');
    await page.locator('#auth-submit').click();
    await page.locator('#app-shell').waitFor({ state: 'visible' });
    const work = await create('works', { code: 'DOC-OB', name: 'Obra documentos', status: 'ATIVA' });
    const category = await create('categories', { name: 'Materiais gerais', description: '' });
    const location = await create('locations', { name: 'Almoxarifado documentos', work_id: work.id });
    const employee = await create('employees', { registration: 'DOC-001', name: 'Ana documentos', job_title: 'Técnica', work_id: work.id, status: 'ATIVO' });
    await page.getByRole('heading', { name: 'Visão geral', exact: true }).waitFor();
    assert.equal(await page.locator('a[href="/documentos?report=dashboard"]').count(), 1);
    assert.equal(await page.locator('#main-nav a[href="/documentos"]').count(), 1);

    // Both zero and positive opening quantities go through the real catalog form.
    await route('cadastros/materials', 'Materiais');
    await page.locator('[data-action=new-catalog]').first().click();
    await modal.waitFor({ state: 'visible' });
    assert.equal(await modal.locator('[name=initial_quantity]').inputValue(), '0');
    assert.equal(await modal.locator('[name=initial_location_id]').isDisabled(), true);
    for (const [key, value] of Object.entries({ code: 'ZERO-DOC', description: 'Material sem saldo', category_id: category.id, unit: 'UN', minimum_stock: 0, status: 'ATIVO' })) await fill(key, value);
    await save();
    assert.deepEqual(await get('movements'), []);
    assert.ok((await get('stock')).every(row => row.quantity === 0 && row.location_id === null), 'Zero initial stock must not create a location balance.');
    await page.locator('[data-action=new-catalog]').first().click();
    for (const [key, value] of Object.entries({ code: 'FORM-DOC', description: 'Material pelo formulário', category_id: category.id, unit: 'KG', minimum_stock: 1, status: 'ATIVO', initial_quantity: '4.125', initial_location_id: location.id, initial_source_type: 'NOTA_FISCAL', initial_source_reference: 'NF-FORM-01' })) await fill(key, value);
    await save();
    const formMaterial = (await get('catalog/materials')).find(row => row.code === 'FORM-DOC');
    assert.equal((await get('stock')).find(row => row.material_id === formMaterial.id).quantity, 4.125);
    await page.locator('[data-action=edit-catalog][data-id="' + formMaterial.id + '"]').click();
    assert.equal(await modal.locator('[name=initial_quantity]').count(), 0, 'Editing catalog must not edit stock.');
    await modal.locator('[data-dialog-close]').first().click();
    await page.locator('[data-action=add-material-stock][data-id="' + formMaterial.id + '"]').click();
    assert.equal(await modal.locator('[name=type]').inputValue(), 'ENTRADA');
    assert.equal(await modal.locator('[name=material_id]').inputValue(), String(formMaterial.id));
    await fill('quantity', '0.875'); await fill('destination_id', location.id); await save();
    assert.equal((await get('stock')).find(row => row.material_id === formMaterial.id).quantity, 5);

    await route('estoque', 'Estoque');
    await page.locator('a[href="/documentos?report=stock"]').click();
    await page.getByRole('heading', { name: 'Importar e exportar', exact: true }).waitFor();
    await page.locator('#report-location option[value="' + location.id + '"]').waitFor({ state: 'attached' });
    assert.equal(await page.locator('#report').inputValue(), 'stock');

    // CSV preview is a rolled-back transaction, then confirmation creates one batch.
    const csv = '\ufeffcodigo;descricao;categoria;unidade;minimo;saldo_inicial;local;tipo_origem;referencia\r\nIMP-DOC;Cimento importado;Materiais gerais;KG;1,125;12,345;Almoxarifado documentos;NOTA_FISCAL;NF-IMPORT-01\r\n';
    const beforePreview = await snapshot();
    await page.locator('#import-file').setInputFiles({ name: 'materiais-documentos.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
    await page.locator('#analyze-import').click();
    await page.locator('#confirm-import').waitFor({ state: 'visible' });
    assert.match(await page.locator('#import-result').innerText(), /1 linha\(s\); 1 válida\(s\)/);
    assert.deepEqual(await snapshot(), beforePreview, 'Preview must not change catalog, balances, movements, loans or audit.');
    await page.screenshot({ path: path.join(output, 'documentos-previa-desktop.png'), fullPage: true });
    const confirmations = [];
    page.on('request', request => { if (request.url().endsWith('/api/import/materials/confirm')) confirmations.push({ data: request.postDataJSON(), key: request.headers()['idempotency-key'] }); });
    const confirmed = page.waitForResponse(response => response.url().endsWith('/api/import/materials/confirm'));
    await page.locator('#confirm-import').evaluate(button => { button.click(); button.click(); });
    const confirmResponse = await confirmed;
    assert.equal(confirmResponse.status(), 200, await confirmResponse.text());
    const confirmResult = await confirmResponse.json();
    await page.locator('#documents-message').filter({ hasText: '1 linha(s) importada(s)' }).waitFor();
    await page.locator('#report-material option').filter({ hasText: 'Cimento importado' }).waitFor({ state: 'attached' });
    assert.equal(confirmations.length, 1, 'Double-click confirmation must send only one request.');
    const imported = (await get('catalog/materials')).find(row => row.code === 'IMP-DOC');
    assert.equal((await get('stock')).find(row => row.material_id === imported.id).quantity, 12.345);
    const afterConfirm = await snapshot();
    const replay = await context.request.post(base + '/api/import/materials/confirm', { headers: { 'X-Compac-Client': 'web', 'Idempotency-Key': confirmations[0].key }, data: confirmations[0].data });
    assert.equal(replay.status(), 200, await replay.text());
    assert.deepEqual(await replay.json(), confirmResult);
    assert.deepEqual(await snapshot(), afterConfirm, 'Retry must not duplicate stock or history.');

    // A responsible employee on CONSUMO records attribution without creating a loan.
    await route('movimentacoes', 'Movimentações');
    assert.equal(await page.locator('a[href="/documentos?report=movements"]').count(), 1);
    await page.locator('[data-action=new-movement]').first().click();
    for (const [key, value] of Object.entries({ type: 'SAIDA', purpose: 'CONSUMO', material_id: imported.id, quantity: '2.345', origin_id: location.id, employee_id: employee.id })) await fill(key, value);
    assert.equal(await modal.locator('[name=due_date]').isDisabled(), true);
    await save();
    assert.deepEqual(await get('loans'), []);
    assert.equal((await get('stock')).find(row => row.material_id === imported.id).quantity, 10);

    await page.goto(base + '/documentos?report=movements');
    await page.locator('#report-material option[value="' + imported.id + '"]').waitFor({ state: 'attached' });
    assert.equal(await page.locator('#report').inputValue(), 'movements');
    await page.locator('#report-material').selectOption(String(imported.id));
    await page.locator('#report-from').fill('2099-01-01'); await page.locator('#report-to').fill('2099-01-31');
    await page.locator('#preview-report').click();
    await page.getByText('Nenhum registro para os filtros escolhidos.', { exact: true }).waitFor();
    await page.locator('#report-from').fill(''); await page.locator('#report-to').fill('');
    assert.equal(await page.locator('#report-result').isHidden(), true, 'Changing filters must hide stale results.');
    await page.locator('#preview-report').click();
    await page.locator('#report-result').filter({ hasText: '2 registro(s).' }).waitFor();

    // All four choices produce real response bytes and browser downloads.
    for (const format of ['pdf', 'xlsx', 'docx', 'csv']) {
      await page.locator('#document-format').selectOption(format);
      const responsePromise = page.waitForResponse(response => response.url().includes('/api/reports/movements/export?'));
      const downloadPromise = page.waitForEvent('download');
      await page.locator('#download-report').click();
      const [response, download] = await Promise.all([responsePromise, downloadPromise]);
      assert.equal(response.status(), 200, await response.text().catch(() => ''));
      assert.match(response.headers()['content-disposition'], new RegExp('filename="compac-movements\\.' + format + '"'));
      assert.equal(download.suggestedFilename(), 'compac-movements.' + format);
      const target = path.join(output, download.suggestedFilename()); await download.saveAs(target);
      const data = fs.readFileSync(target); assert.ok(data.length > 100);
      if (format === 'pdf') assert.equal(data.subarray(0, 5).toString(), '%PDF-');
      else if (format !== 'csv') assert.equal(data.subarray(0, 2).toString(), 'PK');
      else assert.ok(data.toString('utf8').includes('Cimento importado'));
    }
    // Pending old previews must not reopen when the user changes reports.
    await page.locator('#report').selectOption('stock');
    let release, started;
    const gate = new Promise(resolve => { release = resolve; });
    const intercepted = new Promise(resolve => { started = resolve; });
    const stockRoute = /\/api\/reports\/stock(?:\?|$)/;
    await page.route(stockRoute, async route => { const response = await route.fetch(); started(); await gate; await route.fulfill({ response }); });
    await page.locator('#preview-report').click(); await intercepted;
    await page.locator('#report').selectOption('materials'); release();
    await page.locator('#preview-report:not([disabled])').waitFor();
    assert.equal(await page.locator('#report-result').isHidden(), true);
    await page.unroute(stockRoute);

    await page.screenshot({ path: path.join(output, 'documentos-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(output, 'documentos-celular.png'), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Documents mobile overflow');
    await route('cadastros/materials', 'Materiais');
    await page.locator('[data-action=new-catalog]').first().click();
    await modal.locator('[name=initial_quantity]').scrollIntoViewIfNeeded();
    await modal.evaluate(dialog => { dialog.scrollTop = dialog.scrollHeight; });
    await modal.locator('[name=initial_quantity]').waitFor({ state: 'visible' });
    await page.screenshot({ path: path.join(output, 'material-inicial-celular.png'), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Material form mobile overflow');
    assert.deepEqual(errors, []);
    console.log('PASS: saldo inicial zero/positivo, adicionar estoque, CSV prévia sem efeitos + confirmação única/retry, consumo com responsável sem empréstimo, filtros/vazio/prévia stale, PDF/XLSX/DOCX/CSV baixados e mobile. Artifacts: ' + output);
  } catch (error) {
    if (page) { await page.screenshot({ path: path.join(output, 'erro-documentos.png'), fullPage: true }).catch(() => {}); console.error('Diagnostics:', await page.locator('body').innerText().catch(() => '')); }
    throw error;
  } finally {
    if (browser) await browser.close();
    const stopped = new Promise(resolve => child.once('exit', resolve));
    if (child.exitCode === null) { child.kill(); await stopped; }
    fs.rmSync(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exit(1); });
