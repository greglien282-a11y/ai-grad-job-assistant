import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { resolve, dirname, join } from 'node:path'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { spawn, execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { scenarios } from './scenarios.mjs'
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..'), web = join(root,'apps/web')
const require = createRequire(join(web,'package.json')), { chromium, expect } = require('@playwright/test')
const { Document, Packer, Paragraph, Table, TableRow, TableCell } = require('docx')
const out = resolve(process.env.M2_ACCEPTANCE_OUTPUT || join(root,'.e2e/m2-acceptance'))
await mkdir(out,{recursive:true})
const origin='http://127.0.0.1:15201', production='http://127.0.0.1:15202'
const children=[], results=[], failures=[]
const candidate=execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim()
const dirty=Boolean(execFileSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).trim())
function start(args){ const p=spawn(process.execPath,args,{cwd:web,windowsHide:true,env:{...process.env,VITE_PATHWISE_JD_LAB:'synthetic-v1'},stdio:['ignore','pipe','pipe']}); children.push(p); let output=''; p.stdout.on('data',b=>{output+=b});p.stderr.on('data',b=>{output+=b});p.log=()=>output;return p }
async function ready(url,child){ const limit=Date.now()+15000;while(Date.now()<limit){if(child.exitCode!==null)throw Error('local server exited');try{if((await fetch(url)).ok)return}catch{} await new Promise(r=>setTimeout(r,100))}throw Error('local server not ready') }
const dev=start(['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','15201','--strictPort','--force'])
const prod=start(['node_modules/vite/bin/vite.js','preview','--host','127.0.0.1','--port','15202','--strictPort'])
let browser
const encode=raw=>Buffer.from(raw,'utf8')
async function fileFor(s){
 if(s.format==='pdf'){
  const maker=await browser.newPage();await maker.setContent('<meta charset="utf-8"><h1>公开合成简历</h1><div style="display:grid;grid-template-columns:1fr 1fr;gap:40px"><div><h2>教育经历</h2><p>合成大学 · 本科课程 · 应届生。</p><h2>项目经历</h2><p>我编写了Python图像读取脚本。</p></div><div><h2>技能</h2><p>Python课程基础。</p><p>团队负责演示，我只整理记录。</p></div></div>');const b=await maker.pdf({format:'A4'});await maker.close();return b
 }
 if(s.format==='docx') return Packer.toBuffer(new Document({sections:[{properties:{page:{size:{width:11906,height:16838}}},children:[new Paragraph('教育经历'),new Paragraph('合成大学 · 计算机本科课程 · 应届生。'),new Paragraph('项目经历'),new Paragraph('我编写了Python课程脚本。'),new Paragraph('技能'),new Table({rows:[new TableRow({children:[new TableCell({children:[new Paragraph('Python课程基础。')]}),new TableCell({children:[new Paragraph('团队负责演示，我没有参与部署。')]})]})]})]}]}))
 return encode(s.raw)
}
async function privacy(page,effects){
 expect(effects).toEqual([])
 expect(await page.evaluate(async()=>({local:localStorage.length,session:sessionStorage.length,dbs:(await indexedDB.databases()).length,caches:(await caches.keys()).length}))).toEqual({local:0,session:0,dbs:0,caches:0})
 expect(await page.locator('.resume-lab img,.resume-lab script').count()).toBe(0)
}
async function runCase(s){
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),steps=[],effects=[],errors=[],domEvents={click:0,input:0,change:0}; await page.exposeFunction('__m2Count',type=>{domEvents[type]++}); await page.addInitScript(()=>{for(const type of ['click','input','change'])document.addEventListener(type,()=>{void window.__m2Count(type)},true)})
 let manual=0, repeated=0, snapshot='',imported,downloaded,paperText='',completed=false
 page.on('request',r=>{if(r.method()!=='GET'||!r.url().startsWith(origin+'/')||r.url().includes('/api/'))effects.push({method:r.method(),url:r.url()})})
 page.on('pageerror',e=>errors.push(e.message))
 const act=async(name,fn,judgment=false)=>{await fn();steps.push({step:steps.length+1,action:name,manual_judgment:judgment});if(judgment)manual++}
 const result={id:s.id,name:s.name,format:s.format,candidate,dirty,synthetic:true,notes:s.notes,steps}
 try{
  await page.goto(origin+'/resume-lab')
  imported=await fileFor(s);await writeFile(join(out,`${s.id}-input.${s.format==='paste'?'txt':s.format}`),imported)
  await act('导入公开合成简历',async()=>{if(s.format==='paste'){await page.getByRole('textbox',{name:'简历原文',exact:true}).fill(s.raw);await page.getByRole('button',{name:'导入并核对原文',exact:true}).click()}else await page.getByLabel('选择本地文本文件').setInputFiles({name:`public-synthetic-${s.id}.${s.format}`,mimeType:'application/octet-stream',buffer:imported})})
  await expect(page.getByLabel('完整简历原文')).toBeVisible();snapshot=await page.getByLabel('完整简历原文').textContent()
  if(!['pdf','docx'].includes(s.format))expect(snapshot).toBe(s.raw)
  expect(snapshot).toContain('合成大学'); if(s.raw.includes('Python'))expect(snapshot).toContain('Python')
  await act('核对完整文本、限定语及来源',async()=>{expect(snapshot.length).toBeGreaterThan(20);expect(await page.getByText('本地材料和手工声明均未经平台核实；不自动确认、分类或保存到事实库。',{exact:false}).count()).toBeGreaterThan(0)},true)
  if(s.crossQuote){await act('人工核对跨段code-point引用',async()=>{await page.getByLabel('起点 1',{exact:true}).fill('0');await page.getByLabel('终点 1',{exact:true}).fill(String(Array.from(snapshot).length));await page.getByRole('button',{name:'应用段落 1',exact:true}).click();await page.getByRole('button',{name:'确认更换来源并重置岗位'}).click();await expect(page.getByRole('region',{name:'原文与候选结构'}).locator('blockquote').first()).toHaveText(snapshot)},true)}
  if(['pdf','docx'].includes(s.format)){
   await expect(page.getByRole('region',{name:'岗位策略',exact:true})).toHaveCount(0)
   await act('查看解析警告并调整候选顺序',async()=>{await expect(page.getByLabel('文件解析质量')).toContainText('不是文件字节或PDF坐标');await page.getByRole('button',{name:'下移段落 1',exact:true}).click()},true)
   await act('显式确认提取文本已人工核对',()=>page.getByRole('button',{name:'已核对文本、顺序与遗漏，进入岗位草稿'}).click(),true)
  }
  await act('填写岗位名称和合成基本信息',async()=>{await page.getByRole('textbox',{name:'岗位草稿名称',exact:true}).fill(`视觉岗位-${s.id}`);await page.getByLabel('姓名',{exact:true}).fill('公开合成同学');await page.getByLabel('联系信息',{exact:true}).fill('synthetic@example.invalid')})
  await act('输入JD并分析',async()=>{await page.getByRole('textbox',{name:'目标岗位原文',exact:true}).fill(s.jd);await page.getByRole('button',{name:'分析本地岗位',exact:true}).click()})
  await act('人工调整条件描述并保留原引文',async()=>{const field=page.getByLabel(/^条件描述 jd-/).first();await field.fill((await field.inputValue())+'（用户待核对）');await expect(page.getByRole('region',{name:'岗位策略',exact:true})).toContainText('用户调整，原引文未变')},true)
  await act('自评缺口，不让关键词代表能力认证',()=>page.getByLabel(/^我的判断 jd-/).first().selectOption('gap'),true)
  if(s.conflict){result.conflict_controls=await page.getByRole('region',{name:'岗位策略',exact:true}).locator('select:disabled').count();expect(result.conflict_controls).toBeGreaterThan(0)}
  if(s.rejectDuplicate){await act('拒绝重复原句并核对整组阻断',async()=>{const target=page.getByRole('article',{name:/原文对照条目/}).filter({hasText:'我编写了Python脚本。'}).first();await target.getByRole('button',{name:/拒绝本地条目/}).click();const boxes=page.getByRole('article',{name:/原文对照条目/}).filter({hasText:'我编写了Python脚本。'}).getByRole('checkbox');for(const box of await boxes.all())await expect(box).toBeDisabled()},true)}
  const boxes=page.getByRole('checkbox',{name:/选用条目/}),eligible=[];for(let n=0;n<await boxes.count();n++)if(await boxes.nth(n).isEnabled())eligible.push(n)
  expect(eligible.length).toBeGreaterThan(0)
  await act('选用可展示的原文条目',async()=>{for(const n of eligible)await boxes.nth(n).check()},true)
  if((await boxes.count())>1)await act('调整条目展示顺序',async()=>{const last=page.getByRole('button',{name:/上移条目/}).last();if(await last.isEnabled())await last.click()})
  // Choose a safely editable educational source; risky originals are inspected, never rewritten to erase limits.
  const originals=page.getByRole('textbox',{name:/^岗位草稿 \d+$/}),safe=[];for(let i=0;i<await originals.count();i++)if((await originals.nth(i).inputValue()).includes('合成大学')&&!s.crossQuote)safe.push(i)
  if(safe.length){await act('用户修改，保持原文对照与未核实标签',async()=>{const field=originals.nth(safe[0]);await field.fill((await field.inputValue())+'（用户草稿，待核对）')},true)}else await act('修改简历抬头，不删除原文限定语',()=>page.getByLabel('简历抬头说明').fill('课程与学习记录 · 用户草稿'),true)
  await act('选择版式与分页目标',async()=>{await page.getByLabel('简历版式').selectOption(s.id==='S07'?'minimal':'classic');await page.getByLabel('分页目标').selectOption('multiple');await page.getByLabel('排版密度').selectOption('compact')},true)
  const paper=page.getByRole('article',{name:'用户自述简历草稿'});await expect(paper).toContainText('未经平台核实');paperText=await paper.textContent()
  expect(paperText).not.toContain('G4');expect(paperText).not.toContain('导入原文 [');expect(paperText).not.toContain('JD原句');
  await act('分别核对简历输出与来源审查，切换不改变准入',async()=>{await page.getByRole('button',{name:'来源审查',exact:true}).click();await expect(paper).not.toBeVisible();await expect(page.getByRole('region',{name:'来源审查详情'})).toContainText('原始片段：');await page.getByRole('region',{name:'来源审查详情'}).screenshot({path:join(out,`${s.id}-source-review.png`)});await page.getByRole('button',{name:'简历输出',exact:true}).click();expect(await paper.textContent()).toBe(paperText)},true)
  if(s.rejectDuplicate)expect(await paper.locator('.paper-entry>p').allTextContents()).not.toContain('我编写了Python脚本。')
  const download=async(label)=>{let event=page.waitForEvent('download');await page.getByRole('button',{name:'下载本地草稿 JSON'}).click();const d=await event;const raw=await readFile(await d.path());await writeFile(join(out,`${s.id}-${label}.json`),raw);return JSON.parse(raw.toString('utf8'))}
  await act('主动下载完整v3草稿',async()=>{downloaded=await download('saved')},true)
  expect(downloaded.contract).toBe('local-job-resume-draft-v3');expect(downloaded.workbench.source.text).toBe(snapshot)
  for(const q of downloaded.workbench.excerpts)expect(Array.from(snapshot).slice(q.start,q.end).join('')).toBe(q.quote)
  if(['pdf','docx'].includes(s.format)){expect(downloaded.workbench.source.extraction.file_sha256).toBe(createHash('sha256').update(imported).digest('hex'));expect(downloaded.workbench.source.extraction.text_sha256).toBe(createHash('sha256').update(snapshot).digest('hex'))}
  await privacy(page,effects)
  await act('刷新后确认没有自动恢复',async()=>{await page.reload();await expect(page.getByLabel('完整简历原文')).toHaveCount(0)})
  await act('主动导入v3恢复，核对来源和重要配置',async()=>{await page.getByLabel('恢复本地草稿 JSON').setInputFiles(join(out,`${s.id}-saved.json`));await expect(page.getByLabel('完整简历原文')).toHaveText(snapshot);await expect(page.getByLabel('排版密度')).toHaveValue('compact');const restored=await download('restored');expect(restored).toEqual(downloaded)},true)
  await act('触发打印并输出真实Chromium PDF',async()=>{await page.evaluate(()=>{window.print=()=>{document.body.dataset.acceptancePrint='requested'}});await page.getByRole('button',{name:'打印用户草稿 / 保存 PDF'}).click();expect(await page.locator('body').getAttribute('data-acceptance-print')).toBe('requested');await page.pdf({path:join(out,`${s.id}-print.pdf`),format:'A4',preferCSSPageSize:true});await page.getByRole('region',{name:'用户草稿打印'}).screenshot({path:join(out,`${s.id}-print-preview.png`)})},true)
  await act('完成当前岗位三题复习，核对岗位和原文',async()=>{await page.getByRole('button',{name:'开始岗位三题'}).click();for(let n=1;n<=3;n++){await expect(page.getByText(`第 ${n} / 3 题`,{exact:true})).toBeVisible();await expect(page.getByRole('region',{name:'岗位三题复习'})).toContainText('原始片段：');await page.getByLabel('我的复习回答').fill(`公开合成回答${n}：仅描述原材料，不编造项目。`);await page.getByRole('button',{name:n===3?'完成岗位复习':'下一道岗位问题'}).click()}await expect(page.getByText('三题复盘 · 不猜经历、不打分')).toBeVisible()},true)
  const reviewed=await download('reviewed')
  await act('仅改标题与段落分类，保留岗位、草稿、顺序和复习',async()=>{const label=page.getByLabel('段落标题 1',{exact:true});await label.fill((await label.inputValue())+'（已核对）');await page.getByRole('button',{name:'应用段落 1',exact:true}).click();const kept=await download('metadata');expect(kept.roles).toEqual(reviewed.roles);expect(kept.workbench.source).toEqual(reviewed.workbench.source)},true)
  await act('仅改外观不丢失三题回答',async()=>{await page.getByLabel('排版密度').selectOption('comfortable');await page.getByLabel('简历版式').selectOption('minimal');const kept=await download('appearance');expect(kept.roles[0].content.review).toEqual(reviewed.roles[0].content.review);await page.getByLabel('排版密度').selectOption('compact');await page.getByLabel('简历版式').selectOption(s.id==='S07'?'minimal':'classic')})
  if(s.twoRoles){
   const first=(await download('roleA-reviewed')).roles[0],sourceId=downloaded.workbench.source.id
   await act('同源新增第二岗位，无须重复导入',()=>page.getByRole('button',{name:'新增Python后端实习生草稿'}).click(),true)
   await act('第二岗位独立选择、编辑、版式与回答',async()=>{await page.getByLabel('选用条目 1',{exact:true}).check();await page.getByRole('textbox',{name:'岗位草稿 1',exact:true}).fill('合成大学本科课程。（后端岗位用户草稿）');await page.getByLabel('简历版式').selectOption('minimal');await page.getByRole('button',{name:'开始岗位三题'}).click();await page.getByLabel('我的复习回答').fill('第二岗位专属回答，不是视觉岗位回答。')},true)
   const both=await download('two-roles');expect(both.roles).toHaveLength(2);expect(both.roles[0]).toEqual(first);expect(both.workbench.source.id).toBe(sourceId)
   await act('下载两岗位、刷新恢复并逐岗核对',async()=>{await page.reload();await page.getByLabel('恢复本地草稿 JSON').setInputFiles(join(out,`${s.id}-two-roles.json`));await expect(page.getByLabel('我的复习回答')).toHaveValue('第二岗位专属回答，不是视觉岗位回答。');await page.getByLabel('当前岗位').selectOption(first.id);await expect(page.getByText('三题复盘 · 不猜经历、不打分')).toBeVisible();await expect(page.getByLabel('简历版式')).toHaveValue('classic')},true)
   result.second_role_added_actions=steps.slice(-3).map(x=>x.action);repeated=0
  }
  await privacy(page,effects);expect(errors).toEqual([])
  result.document_height_px=await page.evaluate(()=>document.documentElement.scrollHeight); result.print_explanation_points=Array.from((await paper.locator('.paper-label,small,footer').allTextContents()).join('')).length; result.print_total_points=Array.from(paperText).length;
  result.strategy_text=await page.getByRole('region',{name:'可解释岗位建议'}).textContent();result.print_text=paperText
  result.pages=(await readFile(join(out,`${s.id}-print.pdf`))).toString('latin1').match(/\/Type \/Page\b/g)?.length??0
  result.references=downloaded.workbench.excerpts.length;result.quality_warnings=downloaded.workbench.source.extraction?.warnings??[]
  if(['S04','S05'].includes(s.id))await expect(paper).toContainText('背景、计划与限制')
  await page.getByRole('region',{name:'岗位策略',exact:true}).screenshot({path:join(out,`${s.id}-strategy.png`)})
  completed=true
 }catch(e){result.error=String(e?.message??e);await page.screenshot({path:join(out,`${s.id}-failure.png`),fullPage:true}).catch(()=>{});failures.push(s.id)}finally{
  result.dom_events=domEvents;result.journey_completed=completed;result.manual_checkpoints=manual;result.repeated_source_imports=repeated;result.actions=steps.length;result.effects=effects;result.page_errors=errors;results.push(result);await context.close()
  console.log(`${s.id}: ${completed?'COMPLETE':'FAILED'}; actions=${steps.length}; checks=${manual}`)
  await writeFile(join(out,'journeys.json'),JSON.stringify({candidate,synthetic_only:true,real_users:0,results},null,2))
 }
}
try{
 await Promise.all([ready(origin,dev),ready(production,prod)])
 browser=await chromium.launch({channel:process.env.M2_ACCEPTANCE_CHANNEL||(process.platform==='win32'?'chrome':undefined),headless:true})
 for(const s of scenarios)await runCase(s)
 const page=await browser.newPage();await page.goto(production+'/resume-lab');await expect(page.getByText('本地简历实验未启用')).toBeVisible();await expect(page.getByLabel('简历原文')).toHaveCount(0);await page.goto(production+'/jd-lab');await expect(page.getByText('开发预览未启用')).toBeVisible();await page.close()
 await writeFile(join(out,'production.json'),JSON.stringify({candidate,flag_supplied:true,dev_gate_closed:true,jd_gate_closed:true,formal_writes:0},null,2))
}finally{await browser?.close();for(const p of children)p.kill();await writeFile(join(out,'servers.log'),children.map(p=>p.log()).join('\n'))}
if(failures.length)process.exitCode=1
