import { describe, it, expect } from 'vitest'
import {
  isFilterActive,
  toApiFilter,
  filterName,
  type ChordFilter
} from '@renderer/chordFilters'

describe('isFilterActive', () => {
  it('returns false for empty object', () => {
    expect(isFilterActive({})).toBe(false)
  })

  it('returns false when level or name missing', () => {
    expect(isFilterActive({ level: 'phylum', name: '' })).toBe(false)
    expect(isFilterActive({ level: '', name: 'Firmicutes' })).toBe(false)
  })

  it('returns true for populated filter', () => {
    const f: ChordFilter = { level: 'superpathway', name: 'Glycolysis' }
    expect(isFilterActive(f)).toBe(true)
  })
})

describe('toApiFilter', () => {
  it('returns {} when inactive', () => {
    expect(toApiFilter({})).toEqual({})
    expect(toApiFilter({ level: '', name: '' })).toEqual({})
  })

  it('returns filter when active', () => {
    const f: ChordFilter = { level: 'phylum', name: 'Firmicutes' }
    expect(toApiFilter(f)).toEqual(f)
  })
})

describe('filterName', () => {
  it('returns empty string when inactive', () => {
    expect(filterName({})).toBe('')
  })

  it('returns name when active', () => {
    expect(filterName({ level: 'superpathway', name: 'Glycolysis' })).toBe('Glycolysis')
  })
})
