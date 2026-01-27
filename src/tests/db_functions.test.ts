import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  get_parents_at_level,
  get_parents_multilevel,
  get_pathway_info,
  get_superpathway_info
} from '../main/db_functions'

const mockAllResults = vi.hoisted(() => [] as unknown[][])

vi.mock('node:sqlite', () => ({
  DatabaseSync: class MockDatabaseSync {
    prepare() {
      return {
        all: () => mockAllResults.shift() ?? []
      }
    }
  }
}))

describe('db_functions', () => {
  beforeEach(() => {
    mockAllResults.length = 0
  })

  describe('get_parents_at_level', () => {
    it('returns mapping from child to parent names', () => {
      mockAllResults.push([
        { c_name: 'Species_A', p_name: 'Phylum_X', c_id: 1, p_id: 10 },
        { c_name: 'Species_B', p_name: 'Phylum_X', c_id: 2, p_id: 10 },
        { c_name: 'Species_C', p_name: 'Phylum_Y', c_id: 3, p_id: 11 }
      ])
      const result = get_parents_at_level(['Species_A', 'Species_B', 'Species_C'], 'phylum')
      expect(result).toEqual({
        Species_A: 'Phylum_X',
        Species_B: 'Phylum_X',
        Species_C: 'Phylum_Y'
      })
    })

    it('backfills same-rank terms to themselves', () => {
      mockAllResults.push([
        { c_name: 'Bacteria', p_name: null, c_id: 2, p_id: null },
        { c_name: 'Species_A', p_name: 'Bacteria', c_id: 1, p_id: 2 }
      ])
      const result = get_parents_at_level(['Bacteria', 'Species_A'], 'kingdom')
      expect(result).toEqual({
        Bacteria: 'Bacteria',
        Species_A: 'Bacteria'
      })
    })

    it('skips backfill when same-rank term not in categories', () => {
      mockAllResults.push([{ c_name: 'Other', p_name: null, c_id: 99, p_id: null }])
      const result = get_parents_at_level(['Other'], 'kingdom')
      expect(result).toEqual({})
    })

    it('returns empty object when no rows', () => {
      mockAllResults.push([])
      const result = get_parents_at_level(['Unknown'], 'phylum')
      expect(result).toEqual({})
    })
  })

  describe('get_parents_multilevel', () => {
    it('returns array of records with id and per-level parent', () => {
      mockAllResults.push(
        [
          { c_name: 'A', p_name: 'P1', c_id: 1, p_id: 10 },
          { c_name: 'B', p_name: 'P1', c_id: 2, p_id: 10 }
        ],
        [
          { c_name: 'A', p_name: 'C1', c_id: 1, p_id: 100 },
          { c_name: 'B', p_name: 'C1', c_id: 2, p_id: 100 }
        ]
      )
      const result = get_parents_multilevel(['A', 'B'], ['phylum', 'class'])
      expect(result).toEqual([
        { id: 'A', phylum: 'P1', class: 'C1' },
        { id: 'B', phylum: 'P1', class: 'C1' }
      ])
    })
  })

  describe('get_pathway_info', () => {
    it('returns nodes and edges for pathway', () => {
      mockAllResults.push(
        [
          { id: 'n1', label: 'Node1', x: 0, y: 0, type: 'enzyme' },
          { id: 'n2', label: 'Node2', x: 10, y: 10, type: 'compound' }
        ],
        [
          {
            source: 'n1',
            source_label: 'Node1',
            target: 'n2',
            target_label: 'Node2'
          }
        ]
      )
      const result = get_pathway_info(1)
      expect(result).toEqual({
        nodes: [
          { id: 'n1', label: 'Node1', x: 0, y: 0, type: 'enzyme' },
          { id: 'n2', label: 'Node2', x: 10, y: 10, type: 'compound' }
        ],
        edges: [
          {
            source: 'n1',
            source_label: 'Node1',
            target: 'n2',
            target_label: 'Node2'
          }
        ]
      })
    })

    it('returns empty nodes and edges when none exist', () => {
      mockAllResults.push([], [])
      const result = get_pathway_info(999)
      expect(result).toEqual({ nodes: [], edges: [] })
    })
  })

  describe('get_superpathway_info', () => {
    it('returns pathway rows with ec, pathway_id, pathway_name, superpathway', () => {
      mockAllResults.push([
        {
          ec: '1.1.1.1',
          pathway_id: 1,
          pathway_name: 'Glycolysis',
          superpathway: 'Carbohydrate metabolism'
        },
        {
          ec: '2.2.2.2',
          pathway_id: 2,
          pathway_name: 'TCA',
          superpathway: 'Energy metabolism'
        }
      ])
      const result = get_superpathway_info()
      expect(result).toHaveLength(2)
      expect(result[0]).toEqual({
        ec: '1.1.1.1',
        pathway_id: 1,
        pathway_name: 'Glycolysis',
        superpathway: 'Carbohydrate metabolism'
      })
      expect(result[1].superpathway).toBe('Energy metabolism')
    })

    it('returns empty array when no pathway data', () => {
      mockAllResults.push([])
      const result = get_superpathway_info()
      expect(result).toEqual([])
    })
  })
})
