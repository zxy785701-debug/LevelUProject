// Copy the supplied drawing paths without redrawing the original character.
const fs=require('node:fs'),path=require('node:path')
const {chromium}=require('playwright')
const source=process.argv[2] || 'D:/nbproject/test-ClaudeCode/prototype'
const target=path.resolve(__dirname,'../src/assets')
const js=fs.readFileSync(path.join(source,'assets/comic.js'),'utf8')
const base=js.match(/<defs>([\s\S]*?)<\/defs>/)[1]
const drawings=Object.fromEntries([...js.matchAll(/<symbol id="(.*?)" viewBox="(.*?)">([\s\S]*?)<\/symbol>/g)].map(m=>[m[1],`<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="120" height="104" viewBox="${m[2]}"><defs>${base}</defs>${m[3]}</svg>`]))
const tabs=[...js.matchAll(/(home|lib|me):'([^']+)'/g)]
for(const m of tabs)drawings['tab-'+m[1]]=`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#141414" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${m[2]}</svg>`
;(async()=>{
 fs.mkdirSync(target,{recursive:true})
 const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage()
 for(const [name,svg] of Object.entries(drawings)){
   fs.writeFileSync(path.join(target,name+'.svg'),svg)
   const png=await page.evaluate(async svg=>{const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);await image.decode();const c=document.createElement('canvas');c.width=image.width*3;c.height=image.height*3;c.getContext('2d').drawImage(image,0,0,c.width,c.height);return c.toDataURL('image/png').split(',')[1]},svg)
   fs.writeFileSync(path.join(target,name+'.png'),Buffer.from(png,'base64'))
 }
 await page.goto('file:///'+source.replace(/\\/g,'/')+'/01-core-flow.html',{waitUntil:'domcontentloaded'});await page.evaluate(()=>Promise.race([document.fonts.ready,new Promise(r=>setTimeout(r,3000))]))
 for(const [index,name] of [[0,'prototype-01'],[1,'prototype-02'],[5,'prototype-06'],[12,'prototype-13']])await page.locator('.device__frame').nth(index).screenshot({path:path.resolve(__dirname,'../../docs/comic-implementation/screenshots/'+name+'.png')})
 await browser.close();console.log('Imported 4 original mascot expressions, 3 tab icons and reference screenshots.')
})().catch(e=>{console.error(e);process.exit(1)})
