const { chromium } = require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const root=path.resolve(__dirname,'..'), temp=fs.mkdtempSync(path.join(os.tmpdir(),'compac-audit-front-')), base='http://127.0.0.1:8824';
const evidence=path.join(root,'artifacts/audit-frontend');fs.mkdirSync(evidence,{recursive:true});
const child=spawn(root+'/.venv/bin/python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8824'],{cwd:root,env:{...process.env,COMPAC_DB:temp+'/probe.db',DATABASE_URL:'',RENDER:'',COMPAC_COOKIE_SECURE:'0',COMPAC_SETUP_TOKEN:'',COMPAC_REQUIRE_POSTGRES:'',COMPAC_PUBLIC_URL:base,RENDER_EXTERNAL_URL:''},stdio:'ignore'});
let browser;
(async()=>{try {
for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
const ctx=await browser.newContext({viewport:{width:1440,height:1000}}), page=await ctx.newPage();await page.goto(base);await page.locator('#auth-screen').waitFor({state:'visible'});
const report={};
report.contrast=await page.evaluate(()=>{
const lin=v=>{v/=255;return v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4)};
const lum=s=>s.match(/[\d.]+/g).slice(0,3).map(Number).map(lin).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
return ['#auth-description','#auth-help','.auth-security'].map(sel=>{const el=document.querySelector(sel),c=getComputedStyle(el),fg=lum(c.color),bg=1;return {selector:sel,text:el.innerText,color:c.color,fontSize:c.fontSize,background:'rgb(255, 255, 255)',ratio:+((bg+.05)/(fg+.05)).toFixed(2)};});
});
await page.locator('#auth-name').fill('Auditoria Fictícia');await page.locator('#auth-username').fill('audit');await page.locator('#auth-password').fill('Test-Audit-2026!');await page.locator('#auth-submit').click();await page.locator('#app-shell').waitFor({state:'visible'});
report.dashboardQuickActions=await page.locator('.quick-grid').evaluate(grid=>{const p=grid.closest('.panel').getBoundingClientRect();return {panel:{left:p.left,right:p.right},gridWidth:grid.clientWidth,scrollWidth:grid.scrollWidth,children:[...grid.children].map(e=>{const r=e.getBoundingClientRect();return {text:e.innerText,left:r.left,right:r.right,clipped:r.right>p.right};})};});await page.screenshot({path:path.join(evidence,'dashboard1440.png'),fullPage:true});
async function create(entity,data){const r=await ctx.request.post(base+'/api/catalog/'+entity,{headers:{'X-Compac-Client':'web'},data});if(!r.ok())throw Error(await r.text());return (await r.json()).id;}
const category=await create('categories',{name:'Categoria anterior',description:''});
await create('materials',{code:'AUD001',description:'Material fictício',category_id:category,unit:'UN',minimum_stock:0,individualizable:false,status:'ATIVO'});
await page.goto(base+'/#cadastros/materials');await page.getByRole('heading',{name:'Materiais',exact:true}).waitFor();await page.getByText('Categoria anterior',{exact:true}).waitFor();
await page.locator('[data-action=new-catalog]').first().click();await page.locator('#form-dialog').waitFor({state:'visible'});
const cdp=await ctx.newCDPSession(page),ax=await cdp.send('Accessibility.getFullAXTree');report.dialogAX=ax.nodes.filter(n=>n.role?.value==='dialog').map(n=>({role:n.role?.value,name:n.name?.value}));
report.initialStockFields=await page.locator('#modal-form').evaluate(f=>[...f.elements].filter(x=>x.name).map(x=>x.name));
await page.locator('[data-dialog-close]').first().click();
const update=await ctx.request.put(base+'/api/catalog/categories/'+category,{headers:{'X-Compac-Client':'web'},data:{name:'Categoria atualizada',description:''}});report.categoryUpdateHTTP=update.status();
await page.locator('#refresh-button').click();await page.getByRole('heading',{name:'Materiais',exact:true}).waitFor();
report.staleRelationAfterRefresh={oldVisible:await page.getByRole('cell',{name:'Categoria anterior',exact:true}).isVisible(),newVisible:await page.getByRole('cell',{name:'Categoria atualizada',exact:true}).isVisible(),serverCategory:(await (await ctx.request.get(base+'/api/catalog/categories')).json())[0].name};

report.tableBench=[];
for (const n of [100,1000,10000]) {
 const rows=Array.from({length:n},(_,i)=>({id:i+1,code:'SYN'+n+'-'+i,description:'Material sintético '+i,category_id:category,unit:'UN',minimum_stock:0,individualizable:false,status:'ATIVO'}));
 await page.route('**/api/catalog/materials', route=>route.fulfill({json:rows}));
 const started=Date.now();
 await page.locator('#refresh-button').click();
 await page.waitForFunction(n=>document.querySelectorAll('tr[data-search]').length===n,n);
 await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 const renderWallMs=Date.now()-started;
 const filterSyncMs=await page.locator('[data-table-search]').evaluate(input=>{const start=performance.now();input.value='Material sintético 9999';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#page-content').getBoundingClientRect();return +(performance.now()-start).toFixed(2);});
 report.tableBench.push({rows:n,renderWallMs,filterSyncMs});
 await page.unroute('**/api/catalog/materials');
}
await page.setViewportSize({width:390,height:844});await page.locator('#menu-toggle').click();
report.sidebarFocus={activeOnOpen:await page.evaluate(()=>document.activeElement.id)};
await page.keyboard.press('Tab');report.sidebarFocus.activeAfterTab=await page.evaluate(()=>({id:document.activeElement.id,inSidebar:!!document.activeElement.closest('#sidebar')}));
await page.screenshot({path:path.join(evidence,'sidebar-focus.png'),fullPage:true});
console.log(JSON.stringify(report,null,2));fs.writeFileSync(path.join(evidence,'probe-results.json'),JSON.stringify(report,null,2));
}finally{if(browser)await browser.close();child.kill();fs.rmSync(temp,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exit(1)});
