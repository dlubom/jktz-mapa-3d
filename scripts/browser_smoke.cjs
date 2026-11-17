/* Real WebGPU acceptance; no software renderer is substituted silently. */
const {chromium}=require('playwright');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const url=process.argv[2]||'http://127.0.0.1:8768/jktz-mapa-3d/';
const output=path.resolve(process.env.BROWSER_OUTPUT||'output/playwright');
fs.mkdirSync(output,{recursive:true});
const state=page=>page.evaluate(()=>{const s=jktz.getState();delete s.frames;return s;});
async function settled(page){
  await page.waitForFunction(()=>{const s=window.jktz?.getState();return s?.ready || s?.failures?.length;},null,{timeout:120000});
  let last=-1,same=0;
  for(let i=0;i<120;i++){
    await page.waitForTimeout(250);const s=await state(page);
    assert.equal(s.failures.length,0,s.failures.join('; '));
    const active=s.clouds.find(c=>c.key===s.source);
    same=active?.rootLoaded && s.points===last?same+1:0;last=s.points;
    if(same>=4 && s.points>0)return s;
  }
  throw Error('View did not settle');
}
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:false});
  let page;const errors=[], responses=[], invalidHeaders=[];
  try{
    const context=await browser.newContext({viewport:{width:1400,height:900},deviceScaleFactor:1});
    page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    context.on('request',r=>{if(r.headers()['content-type']==='multipart/byteranges')invalidHeaders.push(r.url());});
    context.on('response',r=>responses.push({url:r.url(),status:r.status()}));
    await page.goto(url);const initial=await settled(page);
    const publication=await (await page.request.get(new URL('publication.json',url).href)).json();
    const hasNmt2019=Object.hasOwn(publication.terrain.clouds,'nmt2019');
    const regionalSource=hasNmt2019?'nmt2019':'regional';
    assert.equal(initial.catalogSource.version,publication.catalog.version);
    assert.equal(initial.totalLegs,publication.counts.legs);
    assert.equal(await page.locator('#catalogRelease').textContent(),publication.catalog.version);
    const views=[];
    for(const kind of ['below','above','region']){
      await page.click('#'+kind);const s=await settled(page);views.push(s);
      assert(s.points<=s.pointBudget);
      if(kind==='region'){
        assert.equal(s.renderedLegs,publication.counts.legs);
        assert.equal(s.source,regionalSource);
      }
      await page.screenshot({path:path.join(output,kind+'.png')});
    }
    if(hasNmt2019){
      const cave=await page.evaluate(()=>jktz.getModel().groups.find(g=>g.id==='Wysoka7Progow')?.id);
      if(cave){
        await page.selectOption('#cave',cave);
        for(const kind of ['above','below']){
          await page.click('#'+kind);
          const s=await settled(page);
          assert.equal(s.source,'nmt2019');
          assert.deepEqual(s.clouds.filter(c=>c.visible).map(c=>c.key),['nmt2019']);
          await page.screenshot({path:path.join(output,'nmt2019-'+kind+'.png')});
        }
      }
      await page.click('#region');
      await page.selectOption('#source','regional');
      assert.equal((await settled(page)).source,'regional');
      const newCloudRanges=responses.filter(r=>r.url.includes('/data/nmt2019/') && r.status===206);
      assert(newCloudRanges.some(r=>r.url.endsWith('/hierarchy.bin')));
      assert(newCloudRanges.some(r=>r.url.endsWith('/octree.bin')));
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
    assert.deepEqual(invalidHeaders,[],'GET Range must not send a multipart Content-Type');
    assert(responses.every(r=>[200,206].includes(r.status)),JSON.stringify(responses.filter(r=>r.status>=400)));
    assert(responses.every(r=>new URL(r.url).origin===new URL(url).origin));
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({status:'PASS',url,browser:browser.version(),publication,initial,views,reload,responses,errors,mobile:'Viewport emulation only; no physical phone test'},null,2));
    console.log(JSON.stringify({status:'PASS',url,browser:browser.version(),commit:publication.commit,catalog:publication.catalog.version,legs:publication.counts.legs,output}));
    await context.close();
  }catch(error){
    const current=page ? await state(page).catch(()=>null) : null;
    fs.writeFileSync(path.join(output,'failure.json'),JSON.stringify({status:'FAIL',url,error:String(error),state:current,errors,responses,invalidHeaders},null,2));
    if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
    throw error;
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
