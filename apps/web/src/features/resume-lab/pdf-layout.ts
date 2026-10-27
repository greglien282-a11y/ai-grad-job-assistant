export type Fragment = { str: string; x: number; y: number; width: number; height: number }
// Geometry only suggests reading order, never character offsets in the original file.
export function orderPage(items: Fragment[], width: number): { text: string; columns: boolean } {
  if (items.length > 10000 || !Number.isFinite(width) || width <= 0 || items.some(i => ![i.x, i.y, i.width, i.height].every(Number.isFinite))) throw new Error('layout budget')
  const ordered = [...items].filter(i => i.str.trim()).sort((a, b) => b.y - a.y || a.x - b.x)
  const rows: Fragment[][] = []
  for (const item of ordered) { const last = rows.at(-1); if (last && Math.abs(last[0].y - item.y) <= Math.max(2, Math.min(5, item.height / 3))) last.push(item); else rows.push([item]) }
  const split = width / 2
  const columns = rows.filter(row => row.some(i => i.x < split - 40 && i.x + i.width < split + 10) && row.some(i => i.x > split + 10)).length >= 2
  const line = (row: Fragment[]) => row.sort((a, b) => a.x - b.x).map((i, n, all) => n && i.x - (all[n - 1].x + all[n - 1].width) > 2 ? ' ' + i.str : i.str).join('')
  if (!columns) return { text: rows.map(line).join('\n\n'), columns }
  // Ambiguous spanning headings are kept before both columns and explicitly warned.
  const spanning = rows.filter(r => r.some(i => i.x < split && i.x + i.width > split + 10))
  const body = rows.filter(r => !spanning.includes(r))
  return { text: [...spanning.map(line), ...body.map(r => line(r.filter(i => i.x < split))).filter(Boolean), ...body.map(r => line(r.filter(i => i.x >= split))).filter(Boolean)].join('\n\n'), columns }
}
