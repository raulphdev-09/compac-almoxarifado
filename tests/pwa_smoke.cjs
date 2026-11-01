/* Run with Node.js and the Playwright package installed. Uses a disposable DB.
 * PWA_BASE_URL can target an already-running local server instead.
 * PWA_BROWSER_PATH selects a system Chromium when Playwright has no download.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'compac-pwa-'));
const port = process.env.PWA_TEST_PORT || '8813';
const base = process.env.PWA_BASE_URL || `http://127.0.0.1:${port}`;
const staticCopy = path.join(temp, 'static');
const expectedAssets = [
  '/offline.html', '/static/offline.css', '/static/offline.js', '/static/icon.svg',
  '/static/icons/icon-192.png', '/static/icons/icon-512.png',
  '/static/icons/maskable-512.png', '/static/icons/apple-touch-icon-180.png',
].sort();
let server;
let context;
let serverOutput = '';

async function ready() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(`${base}/health`);
      if (response.ok) return;
    } catch { /* Waiting for the local process. */ }
    if (server?.exitCode != null) throw new Error(`Server exited: ${serverOutput}`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Server did not become healthy: ${serverOutput}`);
}

async function main() {
  if (!process.env.PWA_BASE_URL) {
    const localPython = path.join(root, '.venv', 'bin', 'python');
    fs.cpSync(path.join(root, 'app', 'static'), staticCopy, { recursive: true });
    // Root document routes use a disposable static copy so an update can be
    // tested without editing product source or restarting the server.
    const runner = 'import os; from pathlib import Path; import app.main as application; application.STATIC = Path(os.environ["PWA_SMOKE_STATIC"]); from app.serve import main; main()';
    server = spawn(fs.existsSync(localPython) ? localPython : 'python', ['-c', runner], {
      cwd: root,
      env: {
        ...process.env, PORT: port, COMPAC_DB: path.join(temp, 'smoke.db'),
        COMPAC_COOKIE_SECURE: '0', COMPAC_SETUP_TOKEN: 'local-pwa-smoke-only',
        COMPAC_PUBLIC_URL: base, RENDER: 'false', PWA_SMOKE_STATIC: staticCopy,
        DATABASE_URL: '', COMPAC_REQUIRE_POSTGRES: '',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    server.stdout.on('data', (chunk) => { serverOutput += chunk; });
    server.stderr.on('data', (chunk) => { serverOutput += chunk; });
  }
  await ready();

  const manifestResponse = await fetch(`${base}/manifest.webmanifest`);
  assert.match(manifestResponse.headers.get('content-type'), /application\/manifest\+json/);
  const manifest = await manifestResponse.json();
  assert.equal(manifest.scope, '/');
  assert.equal(manifest.start_url, '/');
  assert.equal(manifest.display, 'standalone');
  for (const [size, purpose] of [['192x192', 'any'], ['512x512', 'any'], ['512x512', 'maskable']]) {
    const icon = manifest.icons.find((item) => item.sizes === size && item.purpose === purpose);
    assert.ok(icon, `Missing ${size} ${purpose} icon`);
    const response = await fetch(new URL(icon.src, base));
    assert.ok(response.ok);
    assert.match(response.headers.get('content-type'), /image\/png/);
    const png = Buffer.from(await response.arrayBuffer());
    const dimension = Number(size.split('x')[0]);
    assert.equal(png.readUInt32BE(16), dimension);
    assert.equal(png.readUInt32BE(20), dimension);
  }
  const workerResponse = await fetch(`${base}/sw.js`);
  assert.match(workerResponse.headers.get('content-type'), /javascript/);
  assert.equal(workerResponse.headers.get('service-worker-allowed'), '/');
  assert.match(workerResponse.headers.get('cache-control'), /no-cache/);

  const executablePath = process.env.PWA_BROWSER_PATH || (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
  // A persistent profile is needed for Chromium's installability check;
  // an incognito context deliberately cannot install applications.
  context = await chromium.launchPersistentContext(path.join(temp, 'browser'), {
    executablePath, headless: true, args: ['--no-sandbox'],
    viewport: { width: 390, height: 844 },
  });
  const page = context.pages()[0] || await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.waitForFunction(() => navigator.serviceWorker.controller);
  const registration = await page.evaluate(async () => {
    const registered = await navigator.serviceWorker.ready;
    return { scope: registered.scope, scriptURL: registered.active.scriptURL };
  });
  assert.equal(registration.scope, `${base}/`);
  assert.equal(registration.scriptURL, `${base}/sw.js`);

  const cdp = await context.newCDPSession(page);
  await cdp.send('Page.enable');
  const installability = await cdp.send('Page.getInstallabilityErrors');
  assert.deepEqual(installability.installabilityErrors, [], 'Chromium installability errors');

  try {
    await page.locator('[data-install-app]:visible').first().click();
  } catch (error) {
    console.error('Boot diagnostics:', errors, await page.locator('body').innerText());
    throw error;
  }
  assert.match(await page.locator('.compac-pwa-dialog').innerText(), /dados exigem internet/i);
  await page.locator('.compac-pwa-dialog-close').click();
  await page.evaluate(() => {
    const event = new Event('beforeinstallprompt', { cancelable: true });
    event.prompt = async () => { window.__compacInstallInvoked = true; };
    event.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
    window.dispatchEvent(event);
  });
  await page.locator('[data-install-app]:visible').first().click();
  await page.locator('.compac-pwa-dialog-actions').getByRole('button', { name: 'Instalar aplicativo', exact: true }).click();
  assert.equal(await page.evaluate(() => window.__compacInstallInvoked), true);

  await page.evaluate(async () => {
    await fetch('/api/auth/status');
    window.__compacFormMarker = 'still-open';
    const input = document.createElement('input');
    input.dataset.pwaSmokeForm = '';
    input.value = 'Rascunho sem enviar';
    document.body.append(input);
  });
  const cacheContents = await page.evaluate(async () => {
    const names = await caches.keys();
    const result = {};
    for (const name of names) result[name] = (await (await caches.open(name)).keys()).map((request) => new URL(request.url).pathname).sort();
    return result;
  });
  assert.deepEqual(Object.keys(cacheContents), ['compac-offline-v1']);
  assert.deepEqual(cacheContents['compac-offline-v1'], expectedAssets);
  await context.setOffline(true);
  await page.locator('.compac-pwa-status').waitFor({ state: 'visible' });
  assert.equal(await page.evaluate(() => window.__compacFormMarker), 'still-open');
  assert.equal(await page.locator('[data-pwa-smoke-form]').inputValue(), 'Rascunho sem enviar');
  assert.equal(await page.evaluate(() => fetch('/api/auth/status').then(() => 'response', () => 'network-error')), 'network-error');
  assert.equal(await page.evaluate(() => fetch('/api/auth/logout', { method: 'POST', headers: { 'X-Compac-Client': 'web' } }).then(() => 'response', () => 'network-error')), 'network-error');
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: 'Vamos reconectar?' }).waitFor();
  assert.match(await page.locator('[data-connection-status]').innerText(), /sem conexão|Rede detectada/);
  assert.ok(await page.locator('[data-offline-retry]').isVisible());
  const offlineOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  assert.equal(offlineOverflow, false, 'Offline page overflow on mobile');
  await context.setOffline(false);
  await page.locator('[data-offline-retry]').click();
  await page.locator('[data-install-app]:visible').first().waitFor();
  assert.deepEqual(errors, [], 'Browser JavaScript errors');

  if (server) {
    await page.evaluate(() => {
      window.__compacUpdateDraft = 'save-before-update';
      const input = document.createElement('input');
      input.dataset.pwaUpdateDraft = '';
      input.value = 'Formulário antes da atualização';
      document.body.append(input);
    });
    fs.appendFileSync(path.join(staticCopy, 'sw.js'), '\n// Disposable smoke test update.\n');
    await page.evaluate(async () => (await navigator.serviceWorker.getRegistration()).update());
    await page.locator('.compac-pwa-update').waitFor({ state: 'visible' });
    await page.waitForFunction(async () => Boolean((await navigator.serviceWorker.getRegistration()).waiting));
    assert.equal(await page.evaluate(() => window.__compacUpdateDraft), 'save-before-update');
    await page.locator('.compac-pwa-update-open').click();
    await page.getByRole('button', { name: 'Agora não', exact: true }).click();
    assert.equal(await page.locator('[data-pwa-update-draft]').inputValue(), 'Formulário antes da atualização');
    await page.locator('.compac-pwa-update-open').click();
    const navigation = page.waitForNavigation({ waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'Recarregar e atualizar', exact: true }).click();
    await navigation;
    assert.equal(await page.evaluate(() => window.__compacUpdateDraft), undefined);
    await page.locator('[data-install-app]:visible').first().waitFor();
  }

  // Emulated user agents verify help copy only, not native iOS installation.
  for (const [agent, expected] of [
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1', 'Safari'],
    ['Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36', 'Chrome'],
  ]) {
    await cdp.send('Emulation.setUserAgentOverride', { userAgent: agent });
    await page.reload({ waitUntil: 'networkidle' });
    await page.locator('[data-install-app]:visible').first().click();
    assert.match(await page.locator('.compac-pwa-dialog').innerText(), new RegExp(expected));
    await page.locator('.compac-pwa-dialog-close').click();
  }
  console.log('PWA OK: Chromium installability, manifest/icons, SW scope, exact public cache, offline GET/POST rejection, form preservation, fallback/retry, Android/iOS help copy.');
  if (server) console.log('SW update OK: pending update preserves the form; reload occurs only after explicit confirmation.');
  console.log('Native Safari/iPhone installation was not tested. No resources were published.');
}

main().catch((error) => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (context) await context.close();
  if (server && server.exitCode == null) {
    server.kill('SIGTERM');
    await new Promise((resolve) => { server.once('exit', resolve); setTimeout(resolve, 3000).unref(); });
  }
  fs.rmSync(temp, { recursive: true, force: true });
});
