import { readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ExternalHyperlink } from 'docx'
const syntheticDocx = () => Packer.toBuffer(new Document({ sections: [{ properties: { page: { size: { width: 11906, height: 16838 } } }, children: [new Paragraph('教育经历'), new Paragraph('公开合成应届生 · 没有实习经历'), new Paragraph('项目经历'), new Paragraph('我编写了Python课程脚本。👩‍💻 é'), new Table({ rows: [new TableRow({ children: [new TableCell({ children: [new Paragraph('团队负责展示')] }), new TableCell({ children: [new Paragraph('我计划学习部署')] })] })] }), new Paragraph({ children: [new ExternalHyperlink({ link: 'https://example.invalid/private', children: [new TextRun('<img src="https://example.invalid/x" onerror="alert(1)">')] })] })] }] }))
for (const format of ['pdf', 'docx'] as const) test(`real ${format} imports locally, review gates analysis, snapshot sources and download recover`, async ({ page, browser }, info) => {
  let buffer: Buffer
  if (format === 'pdf') { const maker = await browser.newPage(); await maker.setContent('<meta charset="utf-8"><h1>项目经历</h1><div style="display:grid;grid-template-columns:1fr 1fr;gap:40px"><div><p>我编写了Python课程脚本。</p><p>👩‍💻 é 无量化指标</p></div><div><p>团队负责演示。</p><p>我计划学习部署。</p></div></div>'); buffer = await maker.pdf({ format: 'A4' }); await maker.close() } else buffer = await syntheticDocx()
  const effects: string[] = []; page.on('request', r => { if (r.method() !== 'GET' || r.url().includes('/api/') || !r.url().startsWith('http://127.0.0.1:15191/')) effects.push(r.url()) })
  await page.goto('/resume-lab'); await page.getByLabel('选择本地文本文件').setInputFiles({ name: `public-synthetic.${format}`, mimeType: 'application/octet-stream', buffer })
  await expect(page.getByLabel('完整简历原文')).toContainText('Python')
  await expect(page.getByRole('region', { name: '岗位策略', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('文件解析质量')).toContainText('不是文件字节或PDF坐标')
  await expect(page.getByLabel('文件解析质量')).toContainText('尚未核对')
  await page.getByRole('button', { name: '下移段落 1', exact: true }).click()
  await page.getByRole('button', { name: '已核对文本、顺序与遗漏，进入岗位草稿' }).click()
  await expect(page.getByRole('region', { name: '岗位策略', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '填入视觉算法实习 JD' }).click(); await page.getByRole('button', { name: '分析本地岗位' }).click()
  await expect(page.locator('.resume-lab img,.resume-lab script')).toHaveCount(0)
  const download = page.waitForEvent('download'); await page.getByRole('button', { name: '下载本地草稿 JSON' }).click(); const saved = await download; await saved.saveAs(info.outputPath('document-draft.json'))
  await page.screenshot({ path: info.outputPath(`resume_${format}_review.png`), fullPage: true })
  expect(effects).toEqual([]); expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
  await page.reload(); await expect(page.getByLabel('完整简历原文')).toHaveCount(0)
  await page.getByLabel('恢复本地草稿 JSON').setInputFiles(info.outputPath('document-draft.json')); await expect(page.getByLabel('完整简历原文')).toContainText('Python')
})
test('scan, page limit, corrupted and unsupported files leave no partial previous resume', async ({ page, browser }) => {
  const maker = await browser.newPage(); await maker.setContent('<div style="height:200px;background:#ddd"></div>'); const scan = await maker.pdf(); await maker.setContent(Array.from({ length: 13 }, () => '<div style="break-after:page">Synthetic page</div>').join('')); const long = await maker.pdf(); await maker.close()
  await page.goto('/resume-lab')
  for (const [name, buffer] of [['encrypted.pdf', readFileSync(new URL('./fixtures/encrypted-synthetic.pdf', import.meta.url))], ['scan.pdf', scan], ['long.pdf', long], ['bad.docx', Buffer.from('PKbroken')], ['old.doc', Buffer.from('old')], ['huge.pdf', Buffer.alloc(5 * 1024 * 1024 + 1)]] as const) {
    await page.getByLabel('选择本地文本文件').setInputFiles({ name, mimeType: 'application/octet-stream', buffer })
    await expect(page.getByRole('alert')).toContainText('未导入'); await expect(page.getByLabel('完整简历原文')).toHaveCount(0); await expect(page.getByRole('region', { name: '岗位策略', exact: true })).toHaveCount(0)
  }
})
