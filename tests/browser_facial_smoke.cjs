/* Local-only browser tests. Fake camera + explicit test-only matcher validate
 * UI/security contracts, never facial accuracy. Native mode must reject pixels
 * without a face. No employee photograph is used or produced. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {spawn, execFileSync} = require('node:child_process');
const {randomBytes} = require('node:crypto');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const python = path.join(root, '.venv/bin/python');
const output = path.join(root, 'artifacts/ponto-fase3');
const prefix = '/api/v1/attendance';

async function scenario(browser, native = false) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'compac-facial-ui-'));
  const port = Number(process.env.COMPAC_FACE_TEST_PORT || '8841') + (native ? 1 : 0);
  const base = 'http://127.0.0.1:' + port;
  const reference = path.join(temp, 'geometric-reference.png');
  execFileSync(python, ['-c', 'from PIL import Image; import sys; Image.new("RGB",(160,160),(50,100,150)).save(sys.argv[1],"PNG")', reference]);
  const child = spawn(python, ['tests/facial_browser_server.py'], {
    cwd: root, env: {...process.env,
      DATABASE_URL: '', COMPAC_DB: path.join(temp, 'demo.db'), COMPAC_REQUIRE_POSTGRES: '',
      RENDER: '', RENDER_EXTERNAL_URL: '', COMPAC_COOKIE_SECURE: '0', COMPAC_PUBLIC_URL: base,
      COMPAC_SETUP_TOKEN: '', COMPAC_ENV: 'test', COMPAC_ATTENDANCE_MODE: 'facial',
      COMPAC_FACE_SUPERVISED: '1', COMPAC_FACE_KEY: randomBytes(32).toString('base64url'),
      COMPAC_BROWSER_FACE_PORT: String(port), COMPAC_BROWSER_NATIVE_FACE: native ? '1' : '0',
      COMPAC_FACE_MODELS_DIR: path.join(root, '.data/face-models'),
    }, stdio: ['ignore', 'ignore', 'pipe'],
  });
  let admin, device;
  let serverError = '';
  child.stderr.on('data', chunk => { serverError += chunk; });
  try {
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(base + '/health')).ok) break; } catch {}
      if (child.exitCode !== null || i === 149) throw Error('Disposable facial server did not start: ' + serverError.slice(-1000));
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    admin = await browser.newContext({viewport: {width: 1440, height: 1050}});
    device = await browser.newContext({permissions: ['camera'], viewport: {width: 1440, height: 1050}});
    const headers = {'X-Compac-Client': 'web', Origin: base};
    async function post(route, data) {
      const reply = await admin.request.post(base + route, {headers, data});
      assert.ok(reply.ok(), await reply.text()); return reply.json();
    }
    await post('/api/auth/setup', {name: 'Administrador fictício', username: 'demo', password: 'Facial-Browser-Test-2026!'});
    const work = await post('/api/catalog/works', {code: 'DEMO', name: 'FICC fictícia', status: 'ATIVA'});
    await post('/api/catalog/employees', {registration: 'FACE-001', name: 'Pessoa fictícia não exibida no terminal', job_title: 'Teste', work_id: work.id, status: 'ATIVO'});
    const adminPage = await admin.newPage(), errors = [];
    adminPage.on('pageerror', error => errors.push(error.message));
    await adminPage.goto(base + '/ponto-facial/configuracao');
    await adminPage.locator('#face-reference-section').waitFor({state: 'visible'});
    await adminPage.locator('#face-registration').fill('FACE-001');
    await adminPage.locator('#face-lookup').click();
    await adminPage.getByText(/Sem referência facial cadastrada/).waitFor();
    await adminPage.locator('#face-image').setInputFiles(reference);
    await adminPage.locator('#face-authorization-basis').fill('Protocolo fictício para teste automatizado de interface.');
    await adminPage.locator('#face-retention-days').fill('7');
    await adminPage.locator('#face-authorization-confirmed').check();
    await adminPage.locator('#face-save').click();
    if (native) {
      await adminPage.locator('#face-message').filter({hasText: /Nenhum rosto/}).waitFor();
      assert.equal((await (await admin.request.get(base + prefix + '/face-reference?registration=FACE-001')).json()).has_reference, false);
      assert.equal((await (await admin.request.get(base + prefix + '/records')).json()).total, 0);
      assert.equal(await adminPage.locator('#face-image').inputValue(), '');
      assert.deepEqual(errors, []);
      console.log('PASS native OpenCV/YuNet/SFace UI rejection: geometric PNG has no face, no reference or mark persisted. No biometric accuracy claim.');
      return;
    }
    await adminPage.locator('#face-message').filter({hasText: /Referência autorizada salva/}).waitFor();
    assert.equal(await adminPage.locator('#face-image').inputValue(), '');
    assert.equal(await adminPage.locator('#face-authorization-confirmed').isChecked(), false);
    assert.equal(await adminPage.locator('#face-authorization-basis').inputValue(), '');
    const saved = await (await admin.request.get(base + prefix + '/face-reference?registration=FACE-001')).json();
    assert.equal(saved.has_reference, true);
    assert.ok(!('image_base64' in saved) && !('encrypted_image' in saved));
    await adminPage.locator('#terminal-work').selectOption(String(work.id));
    await adminPage.locator('#terminal-name').fill('Tablet facial fictício');
    await adminPage.locator('#create-button').click();
    await adminPage.getByRole('cell', {name: 'Tablet facial fictício', exact: true}).waitFor();
    await adminPage.getByRole('button', {name: 'Gerar novo código', exact: true}).click();
    await adminPage.locator('#activation-panel').waitFor({state: 'visible'});
    const code = await adminPage.locator('#activation-code').inputValue();
    assert.ok(code.length >= 32);
    await adminPage.locator('#clear-code').click();
    fs.mkdirSync(output, {recursive: true});
    await adminPage.screenshot({path: path.join(output, 'admin.png'), fullPage: true});

    const page = await device.newPage(), requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (request.method() === 'POST') requests.push({url: request.url(), body: request.postData()});
    });
    await page.goto(base + '/ponto-facial');
    await page.locator('#activation-code').fill(code); await page.locator('#activate-button').click();
    await page.getByRole('heading', {name: 'FICC fictícia', exact: true}).waitFor();
    assert.match(await page.locator('#mode-banner').innerText(), /RECONHECIMENTO FACIAL EXPERIMENTAL/);
    assert.equal(await page.locator('#mode-warning').isVisible(), true);
    assert.equal(await page.locator('#face-status').isVisible(), false);
    await page.locator('#start-camera').click();
    await page.getByText('Câmera ativa. Uma imagem será usada apenas ao solicitar a verificação supervisionada.', {exact: true}).waitFor();
    await page.screenshot({path: path.join(output, 'terminal-desktop.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({path: path.join(output, 'terminal-celular.png'), fullPage: true});
    async function prepare() { await page.locator('#registration').fill('FACE-001'); await page.locator('#supervision').check(); }
    async function reset() { await page.locator('#success').waitFor({state: 'hidden', timeout: 7000}); }
    const verifyRequests = () => requests.filter(item => item.url.endsWith('/terminal/verify-face'));
    await prepare(); await page.locator('#mark-button').click();
    await page.locator('#success').waitFor({state: 'visible'});
    assert.match(await page.locator('#success-title').innerText(), /Correspondência facial confirmada/);
    assert.ok(!(await page.locator('#success').innerText()).includes('simulado'));
    assert.equal(await page.locator('#registration').inputValue(), '');
    assert.equal(await page.locator('#supervision').isChecked(), false);
    assert.equal(verifyRequests().length, 1);
    const body = JSON.parse(verifyRequests()[0].body);
    assert.equal(body.acknowledgement, 'VERIFICACAO_FACIAL_SUPERVISIONADA');
    assert.ok(Buffer.from(body.image_base64, 'base64').subarray(0, 2).equals(Buffer.from([255, 216])));
    assert.ok(!body.image_base64.includes('data:image'));
    await reset();
    const keys = []; let lose = true;
    await page.route('**/api/v1/attendance/terminal/mark', async route => {
      keys.push(route.request().headers()['idempotency-key']);
      assert.ok(!route.request().postData().includes('image_base64'));
      if (lose) { lose = false; await route.fetch(); await route.abort('failed'); }
      else await route.continue();
    });
    await prepare(); await page.locator('#mark-button').click();
    await page.getByText(/Resultado ainda não confirmado/).waitFor();
    assert.equal(await page.locator('#registration').isDisabled(), true);
    assert.equal(verifyRequests().length, 2);
    await page.locator('#mark-button').click(); await page.locator('#success').waitFor({state: 'visible'});
    assert.equal(keys.length, 2); assert.equal(keys[0], keys[1]);
    assert.equal(verifyRequests().length, 2, 'Replaying a mark must not capture/upload a new image');
    const history = await (await admin.request.get(base + prefix + '/records')).json();
    assert.equal(history.total, 2);
    assert.ok(history.items.every(item => item.verification_method === 'FACIAL_EXPERIMENTAL'));
    assert.equal((await device.request.get(base + '/api/users')).status(), 401);
    assert.equal((await device.request.get(base + prefix + '/records')).status(), 401);
    assert.equal(await page.evaluate(() => Object.keys(localStorage).length + Object.keys(sessionStorage).length), 0);
    assert.ok(!(await page.locator('body').innerText()).includes('Pessoa fictícia não exibida no terminal'));
    await reset();
    adminPage.once('dialog', dialog => dialog.accept());
    await adminPage.locator('#face-delete').click();
    await adminPage.locator('#face-message').filter({hasText: /Referência facial excluída/}).waitFor();
    assert.equal((await (await admin.request.get(base + prefix + '/face-reference?registration=FACE-001')).json()).has_reference, false);
    await prepare(); await page.locator('#mark-button').click();
    await page.locator('#message').filter({hasText: /Não foi possível confirmar a identidade/}).waitFor();
    assert.equal(await page.locator('#success').isVisible(), false);
    assert.equal((await (await admin.request.get(base + prefix + '/records')).json()).total, 2);
    assert.deepEqual(errors, []);
    console.log('PASS facial UI with TEST-ONLY adapter: authorized reference, fake camera JPEG, scoped verification/mark, reset, same-key replay without recapture, reference deletion, protected history, desktop/mobile. Does not measure biometric accuracy.');
  } finally {
    if (admin) await admin.close(); if (device) await device.close();
    if (child.exitCode === null) { const stopped = new Promise(resolve => child.once('exit', resolve)); child.kill(); await stopped; }
    fs.rmSync(temp, {recursive: true, force: true});
  }
}

(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true,
    args: ['--no-sandbox', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']});
  try { await scenario(browser); await scenario(browser, true); }
  finally { await browser.close(); }
})().catch(error => { console.error(error.stack); process.exit(1); });
