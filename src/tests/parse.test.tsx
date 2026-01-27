import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as d3 from 'd3'
import {
  sort_by_category,
  make_count_matrix,
  parse_data_callback,
  make_1d_count_matrix,
  group_tax_tree_at_level,
  parse_tax_tree_recursive,
  parse_tax_tree,
  parse_data
} from '../renderer/src/components/parse'

const mockSetState = vi.hoisted(() => vi.fn())
vi.mock('@renderer/store/AppStore', () => ({
  useAppStore: { setState: mockSetState }
}))

describe('parse', () => {
  describe('sort_by_category', () => {
    it('sorts by category index first', () => {
      const getCatIdx = (x: string) => (x === 'a' ? 0 : x === 'b' ? 1 : 2)
      expect(sort_by_category('a', 'c', getCatIdx)).toBe(-1)
      expect(sort_by_category('c', 'a', getCatIdx)).toBe(1)
      expect(sort_by_category('b', 'a', getCatIdx)).toBe(1)
    })

    it('sorts alphabetically when same category', () => {
      const getCatIdx = () => 0
      expect(sort_by_category('apple', 'banana', getCatIdx)).toBe(-1)
      expect(sort_by_category('banana', 'apple', getCatIdx)).toBe(1)
      expect(sort_by_category('same', 'same', getCatIdx)).toBe(0)
    })
  })

  describe('make_count_matrix', () => {
    it('builds symmetric count matrix from data rows', () => {
      const data = [
        {
          'EC#': '1.1.1.1',
          GeneID: 'g1',
          Length: '100',
          Reads: '10',
          RPKM: '1',
          Species_A: 5,
          Species_B: 0
        },
        {
          'EC#': '2.2.2.2',
          GeneID: 'g2',
          Length: '200',
          Reads: '20',
          RPKM: '2',
          Species_A: 0,
          Species_B: 3
        }
      ]
      const index = ['gap_1', '1.1.1.1', '2.2.2.2', 'gap_2', 'Species_A', 'Species_B', 'gap_3']
      const matrix = make_count_matrix(data, index)
      expect(matrix.length).toBe(index.length)
      expect(matrix[0].length).toBe(index.length)
      const ec1Idx = index.indexOf('1.1.1.1')
      const ec2Idx = index.indexOf('2.2.2.2')
      const spAIdx = index.indexOf('Species_A')
      const spBIdx = index.indexOf('Species_B')
      expect(matrix[ec1Idx][spAIdx]).toBe(5)
      expect(matrix[spAIdx][ec1Idx]).toBe(5)
      expect(matrix[ec2Idx][spBIdx]).toBe(3)
      expect(matrix[spBIdx][ec2Idx]).toBe(3)
    })

    it('uses tax_map and ann_map when provided', () => {
      const data = [
        { 'EC#': '1.1.1.1', GeneID: 'g1', Length: '100', Reads: '10', RPKM: '1', spA: 2 }
      ]
      const index = ['gap_1', 'Path1', 'gap_2', 'PhylumX', 'gap_3']
      const taxMap: Record<string, string> = { spA: 'PhylumX' }
      const annMap: Record<string, string> = { '1.1.1.1': 'Path1' }
      const matrix = make_count_matrix(data, index, taxMap, annMap)
      const pathIdx = index.indexOf('Path1')
      const phyIdx = index.indexOf('PhylumX')
      expect(matrix[pathIdx][phyIdx]).toBe(2)
      expect(matrix[phyIdx][pathIdx]).toBe(2)
    })

    it('adds filler node self-weights when matrix has counts', () => {
      const data = [
        { 'EC#': '1.1.1.1', GeneID: 'g1', Length: '100', Reads: '10', RPKM: '1', Sp: 4 }
      ] as Array<object>
      const index = ['gap_1', '1.1.1.1', 'gap_2', 'Sp', 'gap_3']
      const matrix = make_count_matrix(data, index)
      const flat = d3.sum(matrix.flat())
      expect(flat).toBeGreaterThan(0)
      expect(matrix[0][0]).toBeGreaterThan(0)
      expect(matrix[2][2]).toBeGreaterThan(0)
      expect(matrix[4][4]).toBeGreaterThan(0)
    })
  })

  describe('parse_data_callback', () => {
    it('returns inner/outer matrices, index, colors, and maps', () => {
      const data = [
        { 'EC#': '1.1.1.1', GeneID: 'g1', Length: '100', Reads: '10', RPKM: '1', A: 1, B: 2 },
        { 'EC#': '2.2.2.2', GeneID: 'g2', Length: '200', Reads: '20', RPKM: '2', A: 0, B: 1 }
      ]
      const ecMap: Record<string, string> = { '1.1.1.1': 'P1', '2.2.2.2': 'P2' }
      const taxMap: Record<string, string> = { A: 'T1', B: 'T1' }
      const result = parse_data_callback(data, ecMap, taxMap)
      expect(result).toHaveProperty('inner_count_matrix')
      expect(result).toHaveProperty('inner_matrix_index')
      expect(result).toHaveProperty('outer_count_matrix')
      expect(result).toHaveProperty('outer_matrix_index')
      expect(result).toHaveProperty('colors')
      expect(result.tax_map).toEqual(taxMap)
      expect(result.ann_map).toEqual(ecMap)
      expect(result.outer_matrix_index).toContain('gap_1')
      expect(result.outer_matrix_index).toContain('gap_2')
      expect(result.outer_matrix_index).toContain('gap_3')
      expect(result.colors['P1']).toBeDefined()
      expect(result.colors['T1']).toBeDefined()
    })
  })

  describe('make_1d_count_matrix', () => {
    it('aggregates RPKM per tax category', () => {
      const data = [
        { A: 10, B: 20 },
        { A: 30, B: 40 }
      ] as Array<object>
      const taxMap: Record<string, string> = { A: 'Cat1', B: 'Cat2' }
      const result = make_1d_count_matrix(data, taxMap)
      expect(result.counts_idx).toEqual(['Cat1', 'Cat2'])
      expect(result.counts[0]).toBe(d3.mean([10, 30]))
      expect(result.counts[1]).toBe(d3.mean([20, 40]))
    })

    it('ignores zero and missing values', () => {
      const data = [{ A: 0, B: 5 }] as Array<object>
      const taxMap: Record<string, string> = { A: 'C1', B: 'C2' }
      const result = make_1d_count_matrix(data, taxMap)
      expect(result.counts[0]).toBe(d3.mean([]))
      expect(result.counts[1]).toBe(5)
    })
  })

  describe('group_tax_tree_at_level', () => {
    it('groups by level and uses "Unclassified {id}" when missing', () => {
      const tree = [
        { id: 's1', phylum: 'P1', genus: 'G1' },
        { id: 's2', phylum: 'P1', genus: 'G2' },
        { id: 's3', phylum: null, genus: null }
      ] as Array<Record<string, unknown>>
      const groups = group_tax_tree_at_level(tree, 'phylum')
      expect(groups).toHaveLength(2)
      const p1 = groups.find((g) => g.subset_name === 'P1')
      const uncl = groups.find((g) => String(g.subset_name).startsWith('Unclassified'))
      expect(p1?.subset).toHaveLength(2)
      expect(uncl?.subset).toHaveLength(1)
      expect((uncl?.subset[0] as Record<string, unknown>).id).toBe('s3')
    })
  })

  describe('parse_tax_tree_recursive', () => {
    it('returns leaf node with value and percentage at species level', () => {
      const data: Record<string, number> = { s1: 10 }
      const tree = [{ id: 's1' }] as Array<Record<string, unknown>>
      const total = 10
      const out = parse_tax_tree_recursive(data, tree, [], 's1', total)
      expect(out.id).toBe('s1')
      expect(out.label).toBe('s1')
      expect(out.value).toBe(10)
      expect(out.percentage).toBe(1)
    })

    it('returns intermediate node with children when levels remain', () => {
      const data: Record<string, number> = { s1: 5, s2: 5 }
      const tree = [
        { id: 's1', phylum: 'P1', genus: 'G1', species: 's1' },
        { id: 's2', phylum: 'P2', genus: 'G2', species: 's2' }
      ] as Array<Record<string, unknown>>
      const total = 10
      const out = parse_tax_tree_recursive(
        data,
        tree,
        ['phylum', 'genus', 'species'],
        'root',
        total
      )
      expect(out.id).toBe('root')
      expect(out.label).toBe('root')
      expect(out.children).toBeDefined()
      expect(out.children).toHaveLength(2)
      expect(out.children![0].id).toBe('P1')
      expect(out.children![1].id).toBe('P2')
      expect(out.percentage).toBe(1)
    })
  })

  describe('parse_tax_tree', () => {
    it('returns hierarchical tree with percentages', () => {
      const data = [{ s1: 8, s2: 2 }] as Array<object>
      const tree = [
        { id: 's1', phylum: 'P1', genus: 'G1', species: 's1' },
        { id: 's2', phylum: 'P1', genus: 'G1', species: 's2' }
      ] as Array<Record<string, unknown>>
      const out = parse_tax_tree(data, tree, ['phylum', 'genus', 'species'])
      expect(out.id).toBe('root')
      expect(out.label).toBe('root')
      expect(out.percentage).toBe(1)
      expect(out.children).toBeDefined()
    })
  })

  describe('parse_data', () => {
    let sendMock: ReturnType<typeof vi.fn>
    let onceMock: ReturnType<typeof vi.fn>

    beforeEach(() => {
      sendMock = vi.fn()
      onceMock = vi.fn()
      vi.stubGlobal('window', {
        electron: { ipcRenderer: { send: sendMock, once: onceMock } }
      })
      mockSetState.mockClear()
    })

    it('sets loading, sends get-tax-cats, and registers got-tax-cats handler', () => {
      const data = [
        { 'EC#': '1.1.1.1', GeneID: 'g1', Length: '100', Reads: '10', RPKM: '1', Sp: 1 }
      ] as Array<object>
      const ecData = [{ ec: '1.1.1.1', pathway_name: 'P1', superpathway: 'S1' }] as Array<object>

      parse_data(data, ecData, 'phylum', 'pathway')

      expect(mockSetState).toHaveBeenCalledWith({ isLoading: true })
      expect(sendMock).toHaveBeenCalledWith('get-tax-cats', ['Sp'], 'phylum')
      expect(onceMock).toHaveBeenCalledWith('got-tax-cats', expect.any(Function))
    })
  })
})
