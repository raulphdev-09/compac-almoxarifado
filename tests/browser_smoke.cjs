const { chromium } = require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'compac-ui-'));
const port=process.env.COMPAC_TEST_PORT||'8812',base='http://127.0.0.1:'+port;
const output=process.env.COMPAC_TEST_ARTIFACTS||temp;fs.mkdirSync(output,{recursive:true});
const child=spawn(path.join(root,'.venv/bin/python'),['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',port],{cwd:root,env:{...process.env,COMPAC_DB:path.join(temp,'test.db'),RENDER:'',COMPAC_SETUP_TOKEN:'',COMPAC_COOKIE_SECURE:'0',COMPAC_PUBLIC_URL:'',RENDER_EXTERNAL_URL:''},stdio:'ignore'});
let browser,page;
(async()=>{try{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{}if(i===99)throw Error('Servidor indisponível');await new Promise(r=>setTimeout(r,50));}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const ctx=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});page=await ctx.newPage();page.setDefaultTimeout(15000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')console.log('Browser:',m.text().slice(0,300));});
 await page.goto(base);await page.locator('#auth-screen').waitFor({state:'visible'});
 await page.locator('#auth-name').fill('Equipe COMPAC');await page.locator('#auth-username').fill('admin');await page.locator('#auth-password').fill('BrowserTest123!');await page.locator('#auth-submit').click();await page.locator('#app-shell').waitFor({state:'visible'});
 await page.getByRole('heading',{name:'Visão geral',exact:true}).waitFor();
 async function create(entity,data){const r=await ctx.request.post(base+'/api/catalog/'+entity,{headers:{'X-Compac-Client':'web'},data});assert.equal(r.status(),201,await r.text());return (await r.json()).id;}
 const work=await create('works',{code:'OB01',name:'Obra central',status:'ATIVA'}),cat=await create('categories',{name:'Ferramentas',description:''});
 const origin=await create('locations',{name:'Almoxarifado central',work_id:null}),dest=await create('locations',{name:'Depósito da obra',work_id:work});
 await create('employees',{registration:'001',name:'Ana Silva',job_title:'Técnica',work_id:work,status:'ATIVO'});
 async function route(key,heading){await page.goto(base+'/#'+key);await page.getByRole('heading',{name:heading,exact:true}).waitFor();await page.locator('.loading-state,.page-loading').waitFor({state:'hidden'}).catch(()=>{});}
 const modal=page.locator('#form-dialog');
 async function save(){await modal.locator('button[type=submit]').click();await modal.waitFor({state:'hidden'});}
 async function fill(name,value){const e=modal.locator('[name="'+name+'"]');const tag=await e.evaluate(n=>n.tagName);if(tag==='SELECT')await e.selectOption(String(value));else if(await e.getAttribute('type')==='checkbox')await e.setChecked(value);else await e.fill(String(value));}
 await route('cadastros/materials','Materiais');await page.locator('[data-action=new-catalog]').first().click();await modal.waitFor({state:'visible'});
 for(const [k,v] of Object.entries({code:'MAT001',description:'Furadeira de impacto',category_id:cat,unit:'UN',minimum_stock:2,individualizable:true,status:'ATIVO'}))await fill(k,v);await save();
 const material=(await (await ctx.request.get(base+'/api/catalog/materials')).json())[0].id;
 await route('movimentacoes','Movimentações');await page.locator('[data-action=new-movement]').first().click();await modal.waitFor({state:'visible'});
 for(const [k,v] of Object.entries({type:'ENTRADA',material_id:material,quantity:12,destination_id:origin}))await fill(k,v);await save();
 await route('chamados','Chamados');await page.locator('[data-action=new-ticket]').first().click();await modal.waitFor({state:'visible'});
 for(const [k,v] of Object.entries({title:'Reparo na porta do depósito',description:'A porta precisa de manutenção.',priority:'URGENTE',work_id:work,assignee_id:1}))await fill(k,v);await save();
 await page.locator('[data-action=view-ticket]').first().click();await modal.waitFor({state:'visible'});await fill('status','EM_ANDAMENTO');await modal.locator('[data-action=update-ticket]').click();await modal.locator('[data-action=update-ticket]:not([disabled])').waitFor();
 await modal.locator('#ticket-comment').fill('Equipe de manutenção acionada.');await modal.locator('[data-action=comment-ticket]').click();await modal.getByText('Equipe de manutenção acionada.',{exact:true}).waitFor();await modal.locator('[data-dialog-close]').first().click();
 const pages=[['dashboard','Visão geral'],['estoque','Estoque'],['requisicoes','Requisições'],['manutencao','Manutenção'],['despesas','Despesas'],['producao','Produção'],['previsao','Previsão de consumo'],['alertas','Alertas da operação'],['usuarios','Usuários e acessos'],['auditoria','Histórico de auditoria']];
 for(const[key,title]of pages)await route(key,title);
 await route('dashboard','Visão geral');await page.waitForFunction(()=>document.querySelectorAll('#toast-region .toast').length===0);assert.equal(await page.getByText('Nenhum resultado encontrado',{exact:true}).isVisible(),false);await page.screenshot({path:path.join(output,'painel-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'painel-celular.png'),fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Overflow mobile');
 await page.locator('#menu-toggle').click();await page.locator('#main-nav a[href="#chamados"]').click();await page.getByRole('heading',{name:'Chamados',exact:true}).waitFor();
 await page.locator('[data-action=view-ticket]').first().click();await modal.waitFor({state:'visible'});await page.screenshot({path:path.join(output,'chamado-celular.png'),fullPage:true});
 assert.deepEqual(errors,[]);console.log('PASS: cadastro inicial, material pelo formulário, entrada de estoque, chamado/comentário/status, telas e navegação mobile sem erros JavaScript.');
}catch(e){if(page){await page.screenshot({path:path.join(output,'erro-ui.png'),fullPage:true}).catch(()=>{});console.error('Diagnostics:',await page.locator('body').innerText().catch(()=>''));}throw e;}finally{if(browser)await browser.close();const stopped=new Promise(r=>child.once('exit',r));if(child.exitCode===null){child.kill();await stopped;}fs.rmSync(temp,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exit(1)});
