import { describe, it, expect } from 'vitest'
import {
  sort_by_category,
  make_inner_count_matrix,
  parse_graph_data
} from '../server/parse'

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

describe('make_inner_count_matrix', () => {
  it('builds symmetric count matrix using EC# directly', () => {
    const data = [
      { 'EC#': '1.1.1.1', GeneID: 'g1', Length: 100, Reads: 10, RPKM: 1, Species_A: 5, Species_B: 0 },
      { 'EC#': '2.2.2.2', GeneID: 'g2', Length: 200, Reads: 20, RPKM: 2, Species_A: 0, Species_B: 3 }
    ]
    const index = ['gap_1', '1.1.1.1', '2.2.2.2', 'gap_2', 'Species_A', 'Species_B', 'gap_3']
    const matrix = make_inner_count_matrix(data, index)
    const ec1 = index.indexOf('1.1.1.1')
    const ec2 = index.indexOf('2.2.2.2')
    const spA = index.indexOf('Species_A')
    const spB = index.indexOf('Species_B')
    expect(matrix[ec1][spA]).toBe(5)
    expect(matrix[spA][ec1]).toBe(5)
    expect(matrix[ec2][spB]).toBe(3)
    expect(matrix[spB][ec2]).toBe(3)
  })
})

describe('parse_graph_data', () => {
  it('returns inner/outer index, colors, and tax_map (no ann_map)', () => {
    const data = [
      { 'EC#': '1.1.1.1', GeneID: 'g1', Length: 100, Reads: 10, RPKM: 1, A: 1, B: 2 },
      { 'EC#': '2.2.2.2', GeneID: 'g2', Length: 200, Reads: 20, RPKM: 2, A: 0, B: 1 }
    ]
    const ec_map: Record<string, string[]> = {
      '1.1.1.1': ['P1'],
      '2.2.2.2': ['P2']
    }
    const tax_map: Record<string, string> = { A: 'T1', B: 'T1' }
    const result = parse_graph_data({ data, ec_map, tax_map })
    expect(result).toHaveProperty('inner_count_matrix')
    expect(result).toHaveProperty('inner_matrix_index')
    expect(result).toHaveProperty('outer_matrix_index')
    expect(result).not.toHaveProperty('outer_count_matrix')
    expect(result).not.toHaveProperty('ann_map')
    expect(result.tax_map).toEqual(tax_map)
    expect(result.inner_matrix_index).toContain('gap_2')
    expect(result.inner_matrix_index).toContain('gap_3')
    expect(result.outer_matrix_index).toContain('gap_1')
    expect(result.outer_matrix_index).toContain('gap_2')
    expect(result.outer_matrix_index).toContain('gap_3')
    expect(result.colors['P1']).toBeDefined()
    expect(result.colors['T1']).toBeDefined()
    expect(result.colors['1.1.1.1']).toBeDefined()
  })
})
