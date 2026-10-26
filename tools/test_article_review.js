const assert=require('assert').strict,fs=require('fs'),path=require('path');
const {server}=require('./preview_article_review');
if(!process.argv[2]||!process.argv[3])throw new Error('Usage: node tools/test_article_review.js BLOG_OUTPUT SITE_CHECKOUT [REPORT_DIRECTORY]');
const BLOG=path.resolve(process.argv[2]),SITE=path.resolve(process.argv[3]);
const {chromium}=require(path.join(SITE,'node_modules/playwright'));
const {isolate,settled}=require(path.join(SITE,'tools/test_support'));
const report=process.argv[4]?path.resolve(process.argv[4]):fs.mkdtempSync(path.join(require('os').tmpdir(),'blog-article-qa-'));
async function jump(page,selector){await page.locator(selector).first().evaluate(e=>{let y=0;for(let n=e;n;n=n.offsetParent)y+=n.offsetTop;if(typeof scroll!=='undefined'&&scroll.scrollTo)scroll.scrollTo(y-80,{duration:0,disableLerp:true});else e.scrollIntoView({block:'start'});});await page.waitForTimeout(600);}
async function ready(page){await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(600);}
async function check(browser,origin,route,width){
 const ctx=await browser.newContext({viewport:{width,height:1000}});await isolate(ctx,origin);const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(origin+route,{waitUntil:'networkidle'});await ready(page);
  const h2=await page.locator('.post-body h2').evaluateAll(es=>es.map(e=>e.id));
  assert.deepEqual(await page.locator('.post-toc-nav a').evaluateAll(es=>es.map(e=>decodeURIComponent(e.hash.slice(1)))),h2,'All H2 headings, no H3');
  assert.equal(await page.locator('.post-toc-count').textContent(),String(h2.length));
  assert.deepEqual(await page.locator('.post-aside > section').evaluateAll(es=>es.map(e=>e.classList.contains('aside-related')?'related':'cta')),route.includes('/ar/')?['related','cta']:['cta']);
  assert.equal(await page.locator('.blog-body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 254, 248)');
  assert.ok((await page.locator('.aside-cta').evaluate(e=>getComputedStyle(e).backgroundImage)).includes('linear-gradient'));
  assert.equal(await page.locator('.aside-actions a').last().getAttribute('href'),route.includes('/ar/')?'/ar/contact/':'/contact/');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
  await page.screenshot({path:path.join(report,(route.includes('/ar/')?'ar':'en')+'-top-'+width+'.png')});
  await jump(page,'.post-toc');await page.locator('.post-toc-summary').click();
  const link=page.locator('.post-toc-nav a').nth(Math.min(2,h2.length-1));const id=decodeURIComponent((await link.getAttribute('href')).slice(1));
  await link.click();await page.waitForTimeout(1200);let top=await page.locator('.post-body [id]').evaluateAll((es,id)=>es.find(e=>e.id===id).getBoundingClientRect().top,id);
  const panel=await page.locator('.post-toc').boundingBox();
  assert.ok(top>=panel.y+panel.height&&top<850,'TOC keeps chosen heading visible below expanded panel: '+top);
  await page.locator('.post-toc-summary').click();await page.waitForTimeout(300);
  const sticky=await page.locator('.post-toc').boundingBox();assert.ok(sticky.y>=-2&&sticky.y<180,'Contents stays reachable while reading: '+sticky.y);
  await page.screenshot({path:path.join(report,(route.includes('/ar/')?'ar':'en')+'-reading-'+width+'.png')});
  for(const selector of ['.post-image-preview:has(.post-cover)','.post-body .post-image-preview']){
   const image=page.locator(selector).first();if(!await image.count())continue;await jump(page,selector);const href=await image.getAttribute('href');
   await image.click();const dialog=page.locator('.z2o-viewer[open]');assert.equal(await dialog.count(),1);
   assert.equal(await dialog.locator('[data-img]').getAttribute('src'),href);await dialog.locator('[data-img]').evaluate(e=>e.decode());
   assert.equal(await dialog.locator('[data-img]').getAttribute('alt'),await image.locator('img').getAttribute('alt'));
   assert.ok(await dialog.locator('[data-img]').evaluate(e=>e.naturalWidth>0&&getComputedStyle(e).objectFit==='contain'));
   await page.screenshot({path:path.join(report,(route.includes('/ar/')?'ar':'en')+'-preview-'+width+'.png')});
   await page.keyboard.press('Escape');assert.equal(await page.locator('.z2o-viewer[open]').count(),0);assert.ok(await image.evaluate(e=>document.activeElement===e));
   await image.click();await dialog.locator('[data-close]').click();assert.equal(await page.locator('.z2o-viewer[open]').count(),0);
  }
  assert.deepEqual(errors,[]);console.log('PASS article H2/reading/CTA/preview',route,width);
 }finally{await ctx.close();}
}
(async()=>{fs.mkdirSync(report,{recursive:true});const srv=server({blog:BLOG,site:SITE});await new Promise(r=>srv.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+srv.address().port,browser=await chromium.launch();try{
 const routes=['/blog/ar/best-digital-marketing-agency-in-saudi-arabia/','/blog/ar/how-to-market-product-in-saudi-arabia/','/blog/how-to-choose-web-development-company/'];
 const tasks=routes.flatMap(route=>[320,440,834,1440].map(width=>()=>check(browser,origin,route,width)));let i=0;await Promise.all([0,1].map(async()=>{while(i<tasks.length)await tasks[i++]();}));
 const ctx=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});await isolate(ctx,origin);const page=await ctx.newPage();await page.goto(origin+'/ar/services/conversion-rate-optimization/');await ready(page);await page.evaluate(()=>window.__articleWarm=1);
 for(const route of [routes[0],routes[1],routes[2],routes[0]]){await page.evaluate(url=>barba.go(url),route);await settled(page,route);await ready(page);assert.equal(await page.evaluate(()=>window.__articleWarm),1);assert.equal(await page.locator('.z2o-viewer').count(),1);await jump(page,'.post-image-preview');await page.locator('.post-image-preview').first().click();assert.equal(await page.locator('.z2o-viewer[open]').count(),1);await page.keyboard.press('Escape');}
 await ctx.close();console.log('PASS site → article and repeated warm preview lifecycle');
 const plain=await browser.newContext({javaScriptEnabled:false,viewport:{width:440,height:1000}});await isolate(plain,origin);const p=await plain.newPage();
 for(const route of routes){await p.goto(origin+route);await p.locator('.post-toc-summary').click();assert.ok((await p.locator('.post-toc-nav a').count())>0);assert.ok((await p.locator('.post-image-preview').first().getAttribute('href')).endsWith('.webp'));}
 await plain.close();console.log('PASS no-JS contents disclosure and original image links');
}finally{await browser.close();srv.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
