/* Real WebGPU acceptance; no software renderer is substituted silently. */
const {chromium}=require('playwright');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const url=process.argv[2]||'http://127.0.0.1:8768/jktz-mapa-3d/';
const output=path.resolve(process.env.BROWSER_OUTPUT||'output/playwright');
fs.mkdirSync(output,{recursive:true});
const state=page=>page.evaluate(()=>{const s=jktz.getState();delete s.frames;return s;});
async function settled(page){
  await page.waitForFunction(()=>window.jktz?.getState().ready,null,{timeout:120000});
  let last=-1,same=0;
  for(let i=0;i<120;i++){
    await page.waitForTimeout(250);const s=await state(page);
    assert.equal(s.failures.length,0,s.failures.join('; '));
    same=s.points===last?same+1:0;last=s.points;
    if(same>=4 && s.points>0)return s;
  }
  throw Error('View did not settle');
}
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:false});
  try{
    const context=await browser.newContext({viewport:{width:1400,height:900},deviceScaleFactor:1});
    const page=await context.newPage(), errors=[], responses=[];
    page.on('pageerror',e=>errors.push(e.message));
    context.on('response',r=>responses.push({url:r.url(),status:r.status()}));
    await page.goto(url);const initial=await settled(page);
    const publication=await (await page.request.get(new URL('publication.json',url).href)).json();
    assert.equal(initial.catalogSource.version,publication.catalog.version);
    assert.equal(initial.totalLegs,publication.counts.legs);
    assert.equal(await page.locator('#catalogRelease').textContent(),publication.catalog.version);
    const views=[];
    for(const kind of ['below','above','region']){
      await page.click('#'+kind);const s=await settled(page);views.push(s);
      assert(s.points<=s.pointBudget);
      if(kind==='region')assert.equal(s.renderedLegs,publication.counts.legs);
      await page.screenshot({path:path.join(output,kind+'.png')});
    }
    await page.selectOption('#cave',initial.selected);await page.click('#below');await settled(page);
    const before=await state(page);
    await page.mouse.move(1000,500);await page.mouse.down();await page.mouse.move(1080,540,{steps:8});await page.mouse.up();await page.mouse.wheel(0,-180);await page.waitForTimeout(300);
    assert.notDeepEqual((await state(page)).camera,before.camera);
    await page.uncheck('#terrain');await page.waitForTimeout(250);
    assert((await state(page)).clouds.every(c=>!c.visible));
    await page.check('#terrain');await settled(page);
    await page.setViewportSize({width:390,height:844});await settled(page);
    await page.screenshot({path:path.join(output,'mobile-viewport.png')});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.setViewportSize({width:1400,height:900});await page.reload();const reload=await settled(page);
    assert.equal(errors.length,0,errors.join('; '));
    assert(responses.every(r=>[200,206].includes(r.status)),JSON.stringify(responses.filter(r=>r.status>=400)));
    assert(responses.every(r=>new URL(r.url).origin===new URL(url).origin));
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({status:'PASS',url,browser:browser.version(),publication,initial,views,reload,responses,errors,mobile:'Viewport emulation only; no physical phone test'},null,2));
    console.log(JSON.stringify({status:'PASS',url,browser:browser.version(),commit:publication.commit,catalog:publication.catalog.version,legs:publication.counts.legs,output}));
    await context.close();
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
