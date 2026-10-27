import { workbenchSchema, type Workbench } from './import'

// Metadata is never evidence. Compare the complete source snapshot (except the
// explicit text-review acknowledgement) and every citation identity/value.
export function sourceTransition(previous: Workbench, proposed: Workbench) {
  const next = workbenchSchema.parse(proposed)
  const source = (w: Workbench) => {
    const { review: _review, ...rest } = { ...w.source, review: 'review' in w.source ? w.source.review : undefined }
    return { contract: w.contract, ...rest }
  }
  const sorted = <T extends { id: string }>(xs: T[]) => [...xs].sort((a, b) => a.id.localeCompare(b.id))
  const bindings = (w: Workbench) => sorted(w.excerpts.map(({ label: _label, section: _section, ...binding }) => binding))
  const snapshotChanged = JSON.stringify(source(previous)) !== JSON.stringify(source(next))
  const citationsChanged = JSON.stringify(bindings(previous)) !== JSON.stringify(bindings(next))
  const declarationsChanged = JSON.stringify(sorted(previous.manual)) !== JSON.stringify(sorted(next.manual))
  const preserve = !snapshotChanged && !citationsChanged && !declarationsChanged
  const affected = previous.excerpts.filter(e => snapshotChanged || !next.excerpts.some(n => n.id === e.id && n.source_id === e.source_id && n.kind === e.kind && n.start === e.start && n.end === e.end && n.quote === e.quote)).map(e => e.label)
  return { preserve, affected, reason: snapshotChanged ? '原始材料或文本快照身份改变' : citationsChanged ? '引用身份、区间或原句改变' : declarationsChanged ? '手工声明集合改变' : '仅标题、段落分类、顺序或文本核对状态改变' }
}
