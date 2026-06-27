export type ChordFilter = { level: string; name: string }
export type EmptyChordFilter = Record<string, never>

export type ChordFilterValue = ChordFilter | EmptyChordFilter

export const isFilterActive = (f: ChordFilterValue): f is ChordFilter =>
  Boolean(f.level?.trim() && f.name?.trim())

export const toApiFilter = (f: ChordFilterValue): ChordFilter | EmptyChordFilter =>
  isFilterActive(f) ? f : {}

export const filterName = (f: ChordFilterValue): string =>
  isFilterActive(f) ? f.name : ''
