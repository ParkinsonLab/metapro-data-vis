import { describe, it, expect } from 'vitest'
import { get_delta } from '../main/data_functions'

// describe('parsed_data_to_df', () => {
//   it('extracts annotation×taxon matrix using gap_1 to split tax vs annotation labels', () => {
//     const result = parsed_data_to_df({
//       count_matrix: [
//         [0, 0, 0, 0, 0, 0, 0],
//         [0, 0, 0, 0, 1, 3, 0],
//         [0, 0, 0, 0, 2, 4, 0],
//         [0, 0, 0, 0, 0, 0, 0],
//         [0, 1, 2, 0, 0, 0, 0],
//         [0, 3, 4, 0, 0, 0, 0],
//         [0, 0, 0, 0, 0, 0, 0]
//       ],
//       index: ['gap_0', 't1', 't2', 'gap_1', 'a1', 'a2', 'gap_3']
//     })
//     expect(result).toBeInstanceOf(dfd.DataFrame)
//     expect(Array.from(result.columns)).toEqual(['t1', 't2'])
//     expect(Array.from(result.index)).toEqual(['a1', 'a2'])
//     const json = dfd.toJSON(result, { format: 'row' })
//     expect(json).toEqual({ t1: [1, 3], t2: [2, 4] })
//   })
// })

describe('get_delta', () => {
  it('returns df_1 minus df_2 for matching EC# and comparable columns', () => {
    const df_1 = [
      {
        'EC#': '0.0.0.0',
        Bacteria: 1000
      }
    ]
    const df_2 = [
      {
        'EC#': '0.0.0.0',
        Bacteria: 2000
      }
    ]
    const result = get_delta(df_1, df_2)
    expect(result).toHaveLength(1)
    expect(result[0]['EC#']).toBe('0.0.0.0')
    expect(result[0]['Bacteria']).toBe(-1000)
  })

  it('exempts key_cols from comparison (keeps values from source)', () => {
    const df_1 = [
      {
        'EC#': '1.1.1.1',
        Bacteria: 500
      }
    ]
    const df_2 = [
      {
        'EC#': '1.1.1.1',
        Bacteria: 300
      }
    ]
    const result = get_delta(df_1, df_2)
    expect(result[0]['Bacteria']).toBe(200) // 500 - 300
  })

  it('treats missing column as 0 (column only in one df)', () => {
    const df_1 = [
      {
        'EC#': 'X',
        Bacteria: 100,
        Archaea: 50
      }
    ]
    const df_2 = [
      {
        'EC#': 'X',
        Bacteria: 80
      }
    ]
    const result = get_delta(df_1, df_2)
    expect(result[0]['Bacteria']).toBe(20) // 100 - 80
    expect(result[0]['Archaea']).toBe(50) // 50 - 0 (Archaea only in df_1)
  })

  it('returns all unique EC# from both dataframes', () => {
    const df_1 = [
      {
        'EC#': '1.1.1.1',
        Bacteria: 10
      }
    ]
    const df_2 = [
      {
        'EC#': '2.2.2.2',
        Bacteria: 20
      }
    ]
    const result = get_delta(df_1, df_2) as Record<string, unknown>[]
    expect(result).toHaveLength(2)
    const ecs = result.map((r) => r['EC#']).sort()
    expect(ecs).toEqual(['1.1.1.1', '2.2.2.2'])
    const r1 = result.find((r) => r['EC#'] === '1.1.1.1')
    const r2 = result.find((r) => r['EC#'] === '2.2.2.2')
    expect(r1!['Bacteria']).toBe(10) // 10 - 0
    expect(r2!['Bacteria']).toBe(-20) // 0 - 20
  })

  it('matches expected result for data_1 vs data_2 (deltas and columns from both)', () => {
    const data_1 = [
      {
        'EC#': '0.0.0.0',
        Bacteria: 1000,
        Virus: 1000
      },
      {
        'EC#': '1.1.1.1',
        Bacteria: 500,
        Virus: 750
      }
    ]
    const data_2 = [
      {
        'EC#': '0.0.0.0',
        Bacteria: 3000,
        Archea: 500
      },
      {
        'EC#': '1.1.1.1',
        Bacteria: 2000,
        Archea: 250
      }
    ]
    // Columns only in one df are kept as-is (no subtraction). Bacteria/Virus from df_1 - df_2; Archea only in df_2.
    const expected_result = [
      {
        'EC#': '0.0.0.0',
        Bacteria: -2000,
        Virus: 1000,
        Archea: 500
      },
      {
        'EC#': '1.1.1.1',
        Bacteria: -1500,
        Virus: 750,
        Archea: 250
      }
    ]
    const result = get_delta(data_1, data_2)
    expect(result).toEqual(expected_result)
  })
})
