/* Fake-camera/local-only terminal tests. Never uses a real employee photograph. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..'), temp = fs.mkdtempSync(path.join(os.tmpdir(), 'compac-terminal-ui-'));
const base = 'http://127.0.0.1:' + (process.env.COMPAC_TERMINAL_TEST_PORT || '8837');
const child = spawn(path.join(root, '.venv/bin/python'), ['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',new URL(base).port], {
  cwd:root,env:{...process.env,DATABASE_URL:'',COMPAC_DB:path.join(temp,'demo.db'),COMPAC_REQUIRE_POSTGRES:'',RENDER:'',RENDER_EXTERNAL_URL:'',COMPAC_COOKIE_SECURE:'0',COMPAC_PUBLIC_URL:base,COMPAC_SETUP_TOKEN:'',COMPAC_ENV:'test',COMPAC_ATTENDANCE_MODE:'demo'},stdio:'ignore',
});
let browser, page;
(async()=>{try {
  for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{}if(i===99)throw Error('Local test server unavailable');await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
  const admin=await browser.newContext(), device=await browser.newContext({permissions:['camera'],viewport:{width:1440,height:1050}});
  const headers={'X-Compac-Client':'web',Origin:base};
  async function post(path,data){const r=await admin.request.post(base+path,{headers,data});assert.ok(r.ok(),await r.text());return r.json();}
  await post('/api/auth/setup',{name:'Administrador fictício',username:'demo',password:'Terminal-Test-2026!'});
  const work=await post('/api/catalog/works',{code:'DEMO',name:'FICC fictícia',status:'ATIVA'});
  await post('/api/catalog/employees',{registration:'DEMO-001',name:'Pessoa fictícia não exibida',job_title:'Teste',work_id:work.id,status:'ATIVO'});
  const adminPage=await admin.newPage();await adminPage.goto(base+'/ponto-facial/configuracao');
  await adminPage.locator('#terminal-work').selectOption(String(work.id));await adminPage.locator('#terminal-name').fill('Tablet fictício');
  await adminPage.locator('#create-button').click();await adminPage.getByRole('cell',{name:'Tablet fictício',exact:true}).waitFor();
  await adminPage.getByRole('button',{name:'Gerar novo código',exact:true}).click();await adminPage.locator('#activation-panel').waitFor({state:'visible'});
  const code=await adminPage.locator('#activation-code').inputValue();assert.ok(code.length>=32);
  page=await device.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const sent=[];page.on('request',request=>{if(request.method()==='POST')sent.push({url:request.url(),body:request.postData()});});
  await page.goto(base+'/ponto-facial');await page.locator('#activation-panel').waitFor({state:'visible'});
  await page.locator('#activation-code').fill(code);await page.locator('#activate-button').click();await page.getByRole('heading',{name:'FICC fictícia',exact:true}).waitFor();
  assert.equal(await page.locator('#activation-code').inputValue(),'');
  await page.locator('#start-camera').click();await page.getByText('Câmera ativa. Pré-visualização local, sem identificação facial.',{exact:true}).waitFor();
  const output=path.join(root,'artifacts/ponto-fase2');fs.mkdirSync(output,{recursive:true});
  await page.screenshot({path:path.join(output,'terminal-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(output,'terminal-celular.png'),fullPage:true});
  async function prepare(){await page.locator('#registration').fill('DEMO-001');await page.locator('#supervision').check();}
  async function waitReset(){await page.locator('#success').waitFor({state:'hidden',timeout:7000});}
  await prepare();await page.locator('#mark-button').click();await page.locator('#success').waitFor({state:'visible'});
  assert.equal(await page.locator('#registration').inputValue(),'');assert.equal(await page.locator('#supervision').isChecked(),false);
  await waitReset();
  const keys=[];let lose=true;
  await page.route('**/api/v1/attendance/terminal/mark',async route=>{
    keys.push(route.request().headers()['idempotency-key']);
    if(lose){lose=false;await route.fetch();await route.abort('failed');}else await route.continue();
  });
  await prepare();await page.locator('#mark-button').click();await page.getByText(/Resultado ainda não confirmado/).waitFor();
  assert.equal(await page.locator('#registration').isDisabled(),true);
  assert.equal(await page.locator('#mark-fields').evaluate(element=>element.disabled),true);
  await page.locator('#mark-button').click();await page.locator('#success').waitFor({state:'visible'});
  assert.equal(keys.length,2);assert.equal(keys[0],keys[1]);
  const history=await (await admin.request.get(base+'/api/v1/attendance/records')).json();assert.equal(history.total,2);
  await waitReset();await device.setOffline(true);await page.getByText(/Sem internet. Nenhum ponto será enfileirado/).waitFor();
  assert.equal(await page.locator('#mark-button').isDisabled(),true);await device.setOffline(false);await page.waitForTimeout(300);
  assert.equal((await (await admin.request.get(base+'/api/v1/attendance/records')).json()).total,2);
  assert.equal((await device.request.get(base+'/api/users')).status(),401);
  assert.equal((await device.request.get(base+'/api/v1/attendance/records')).status(),401);
  assert.equal(await page.evaluate(()=>Object.keys(localStorage).length+Object.keys(sessionStorage).length),0);
  assert.ok(sent.every(r=>!r.body||!/("image"|"photo"|data:image|face_verified)/.test(r.body)));
  await page.addInitScript(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Fake denial','NotAllowedError');};});
  await page.reload();await page.locator('#terminal-panel').waitFor({state:'visible'});await page.locator('#start-camera').click();
  await page.getByText(/Permissão de câmera negada/).waitFor();assert.equal(await page.locator('#mark-button').isDisabled(),true);
  await page.evaluate(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Fake missing camera','NotFoundError');};});
  await page.locator('#start-camera').click();await page.getByText(/Nenhuma câmera encontrada/).waitFor();
  const terminals=await (await admin.request.get(base+'/api/v1/attendance/terminals')).json();await post('/api/v1/attendance/terminals/'+terminals.items[0].id+'/revoke');
  await page.reload();await page.locator('#activation-panel').waitFor({state:'visible'});assert.equal(await page.locator('#terminal-panel').isVisible(),false);
  assert.ok(!(await page.locator('body').innerText()).includes('Pessoa fictícia não exibida'));
  assert.deepEqual(errors,[]);
  console.log('PASS: admin setup, scoped activation, fake camera preview, simulated mark/reset, lost-response replay, offline no auto-send, denied/missing camera, revocation, no worker history/images/storage, desktop/mobile.');
}finally{if(browser)await browser.close();const stopped=new Promise(r=>child.once('exit',r));if(child.exitCode===null){child.kill();await stopped;}fs.rmSync(temp,{recursive:true,force:true});}})().catch(error=>{console.error(error.stack);process.exit(1);});
