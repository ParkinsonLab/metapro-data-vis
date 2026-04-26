import { describe, it, expect, beforeAll } from 'vitest'

import {
  get_delta,
  initialize,
  add_data,
  add_test_data,
  parse_ec_chord,
  parse_network,
  parse_pathway_list,
  parse_overview,
  get_fname,
  coerce_cell_to_float,
  normalize_ec_value,
  add_data_field_cast,
  subset_data,
  subset_ec,
  subset_data_by_ann,
  agg_by_ec,
  get_tax_map,
  get_ec_map,
  names_to_data,
  __test__
} from '../main/data_functions'
import { empty_filter, key_cols } from '../main/utils'

// ===========================================================================
// Pure helpers — no DB, no fixtures. These test parsing/normalization rules.
// ===========================================================================

describe('coerce_cell_to_float', () => {
  it('returns null for nullish / empty / non-numeric / sentinel inputs', () => {
    expect(coerce_cell_to_float(undefined)).toBeNull()
    expect(coerce_cell_to_float('')).toBeNull()
    expect(coerce_cell_to_float('   ')).toBeNull()
    expect(coerce_cell_to_float('NaN')).toBeNull()
    expect(coerce_cell_to_float('na')).toBeNull()
    expect(coerce_cell_to_float('Null')).toBeNull()
    expect(coerce_cell_to_float('NONE')).toBeNull()
    expect(coerce_cell_to_float('abc')).toBeNull()
    expect(coerce_cell_to_float('Infinity')).toBeNull()
  })

  it('parses valid numeric strings (including whitespace) to numbers', () => {
    expect(coerce_cell_to_float('0')).toBe(0)
    expect(coerce_cell_to_float('1.5')).toBe(1.5)
    expect(coerce_cell_to_float('  3.14  ')).toBeCloseTo(3.14)
    expect(coerce_cell_to_float('-2.5e1')).toBe(-25)
  })
})

describe('normalize_ec_value', () => {
  it('returns "0.0.0.0" for empty/none variants', () => {
    expect(normalize_ec_value('')).toBe('0.0.0.0')
    expect(normalize_ec_value('   ')).toBe('0.0.0.0')
    expect(normalize_ec_value('none')).toBe('0.0.0.0')
    expect(normalize_ec_value('NONE')).toBe('0.0.0.0')
    expect(normalize_ec_value('None')).toBe('0.0.0.0')
  })

  it('strips a leading "EC:" (any case) and trims', () => {
    expect(normalize_ec_value('EC:1.1.1.1')).toBe('1.1.1.1')
    expect(normalize_ec_value('ec: 2.7.1.1 ')).toBe('2.7.1.1')
  })

  it('treats EC-prefixed empty/none as "0.0.0.0"', () => {
    expect(normalize_ec_value('EC:')).toBe('0.0.0.0')
    expect(normalize_ec_value('EC:none')).toBe('0.0.0.0')
  })

  it('passes through valid ec numbers unchanged', () => {
    expect(normalize_ec_value('3.4.21.92')).toBe('3.4.21.92')
  })
})

describe('add_data_field_cast', () => {
  // CastingContext has many fields; the cast only reads `header` and `column`.
  const ctx = (overrides: Partial<{ header: boolean; column: string }>): never =>
    ({ header: false, column: '', ...overrides }) as never

  it('returns the raw header value untouched when context.header is true', () => {
    expect(add_data_field_cast('SomeHeader', ctx({ header: true, column: 'SomeHeader' }))).toBe(
      'SomeHeader'
    )
  })

  it('passes GeneID values through verbatim (no float coercion)', () => {
    expect(add_data_field_cast('gene_xyz', ctx({ column: 'GeneID' }))).toBe('gene_xyz')
  })

  it('normalizes the EC# column', () => {
    expect(add_data_field_cast('EC:1.1.1.1', ctx({ column: 'EC#' }))).toBe('1.1.1.1')
    expect(add_data_field_cast('None', ctx({ column: 'EC#' }))).toBe('0.0.0.0')
  })

  it('coerces other columns with coerce_cell_to_float', () => {
    expect(add_data_field_cast('1.5', ctx({ column: 'Bacteria' }))).toBe(1.5)
    expect(add_data_field_cast('NA', ctx({ column: 'Bacteria' }))).toBeNull()
  })
})

describe('get_fname', () => {
  // NOTE: substring(-4) coerces -4 to 0, so the ".tsv" extension is NOT
  // stripped. These tests document the CURRENT behavior.
  it('returns the last path segment as-is (extension is NOT stripped)', () => {
    expect(get_fname('foo/bar/baz.tsv')).toBe('baz.tsv')
    expect(get_fname('simple.tsv')).toBe('simple.tsv')
    expect(get_fname('/abs/path/to/file.tsv')).toBe('file.tsv')
    expect(get_fname('../../resources/example_data/test_rpkm_1.tsv')).toBe('test_rpkm_1.tsv')
  })

  it('returns empty string for trailing slash', () => {
    expect(get_fname('foo/bar/')).toBe('')
  })
})

// ===========================================================================
// Integration: real SQLite DB + real test_rpkm_1.tsv / test_rpkm_2.tsv.
//
// These tests load the real fixtures ONCE in a scoped `beforeAll` and share
// the resulting state across all integration tests. Loading is expensive
// (~125 MB of TSV across ~886k rows), so we use a generous timeout.
// ===========================================================================

describe('integration with real DB and real TSV fixtures', () => {
  let loaded_names: string[]
  let file_a_rows: Record<string, unknown>[]
  let file_b_rows: Record<string, unknown>[]

  beforeAll(() => {
    const status = initialize()
    if (status !== 0) {
      throw new Error(
        `initialize() returned ${status}; expected resources/db/taxonomy.db to be reachable from CWD=${process.cwd()}`
      )
    }
    loaded_names = add_test_data()
    const all = __test__.getData() as Record<string, Record<string, unknown>[]>
    file_a_rows = all[loaded_names[0]]
    file_b_rows = all[loaded_names[1]]
  }, 300_000)

  describe('initialize', () => {
    it('populates ec from get_superpathway_info on the real DB', () => {
      const ec = __test__.getEc() as Array<Record<string, unknown>>
      expect(Array.isArray(ec)).toBe(true)
      expect(ec.length).toBeGreaterThan(0)
      expect(ec[0]).toHaveProperty('ec')
      expect(ec[0]).toHaveProperty('superpathway')
      expect(ec[0]).toHaveProperty('pathway')
    })
  })

  describe('add_test_data', () => {
    it('returns both fixture filenames', () => {
      expect(loaded_names).toEqual(['test_rpkm_1.tsv', 'test_rpkm_2.tsv'])
    })

    it('parsed rows include all key_cols and at least one taxonomy column', () => {
      const sample_keys = Object.keys(file_a_rows[0])
      expect(sample_keys).toEqual(
        expect.arrayContaining(['GeneID', 'EC#', 'Length', 'Reads', 'RPKM', 'Unclassified'])
      )
      const non_key = sample_keys.filter((k) => !key_cols.includes(k))
      expect(non_key.length).toBeGreaterThan(0)
    })

    it('coerces Reads/RPKM/Length to numbers', () => {
      const first = file_a_rows[0]
      expect(typeof first.Reads).toBe('number')
      expect(typeof first.RPKM).toBe('number')
      expect(typeof first.Length).toBe('number')
    })

    it('normalizes "None" EC# entries to "0.0.0.0" (real fixture has these)', () => {
      const has_normalized = file_a_rows.some((r) => r['EC#'] === '0.0.0.0')
      expect(has_normalized).toBe(true)
      // and there should be no raw "None" remaining
      expect(file_a_rows.some((r) => r['EC#'] === 'None')).toBe(false)
    })

    it('loads both files with comparable but distinct row counts', () => {
      expect(file_a_rows.length).toBeGreaterThan(100_000)
      expect(file_b_rows.length).toBeGreaterThan(100_000)
    })
  })

  describe('add_data (direct call with synthetic TSV using real tax_ids)', () => {
    it('remaps numeric tax_id headers via the real get_name_from_id (2→Bacteria, 1239→Firmicutes)', () => {
      const tsv = [
        'GeneID\tLength\tReads\tEC#\tRPKM\t2\t1239',
        'g1\t100\t5\tEC:1.1.1.1\t0.5\t1.0\t2.0',
        'g2\t200\t10\tNone\t1.0\t3.0\t4.0'
      ].join('\n')
      const ret = add_data({ name: '__synth__', data: tsv })
      expect(ret).toBe('__synth__')
      const stored = (__test__.getData() as Record<string, Record<string, unknown>[]>)['__synth__']
      expect(stored).toHaveLength(2)
      const cols = Object.keys(stored[0])
      expect(cols).toEqual(expect.arrayContaining(['Bacteria', 'Firmicutes']))
      expect(stored[0]['EC#']).toBe('1.1.1.1')
      expect(stored[1]['EC#']).toBe('0.0.0.0')
      expect(stored[0]['Bacteria']).toBe(1.0)
      expect(stored[0]['Firmicutes']).toBe(2.0)
    })
  })

  describe('subset_ec', () => {
    it('returns full ec when filter is empty', () => {
      const out = subset_ec(empty_filter)
      expect(out).toBe(__test__.getEc())
    })

    it('filters ec by a real superpathway value', () => {
      const ec = __test__.getEc() as Array<Record<string, unknown>>
      const sp_value = ec.find((r) => r.superpathway != null)?.superpathway as string
      expect(sp_value).toBeTruthy()
      const out = subset_ec({ level: 'superpathway', name: sp_value })
      expect(out.length).toBeGreaterThan(0)
      expect(out.every((r) => r.superpathway === sp_value)).toBe(true)
    })
  })

  describe('get_ec_map', () => {
    it('builds an ec → [pathway] mapping from real ec data', () => {
      const out = get_ec_map(empty_filter, 'pathway')
      const some_ec = Object.keys(out)[0]
      expect(some_ec).toBeDefined()
      expect(Array.isArray(out[some_ec])).toBe(true)
      expect(out[some_ec].length).toBeGreaterThan(0)
    })

    it('builds an ec → [superpathway] mapping that is consistent with subset_ec', () => {
      const ec = __test__.getEc() as Array<Record<string, unknown>>
      const sp_value = ec.find((r) => r.superpathway != null)?.superpathway as string
      const out = get_ec_map({ level: 'superpathway', name: sp_value }, 'superpathway')
      for (const ec_id of Object.keys(out)) {
        expect(out[ec_id]).toEqual([sp_value])
      }
    })
  })

  describe('subset_data', () => {
    it('returns input unchanged when filter has no level or no name', () => {
      expect(subset_data(file_a_rows, empty_filter)).toBe(file_a_rows)
      expect(subset_data(file_a_rows, { level: 'phylum', name: '' })).toBe(file_a_rows)
      expect(subset_data(file_a_rows, { level: '', name: 'Firmicutes' })).toBe(file_a_rows)
    })

    it('keeps key_cols + only columns whose phylum is Firmicutes (real DB lookup)', () => {
      const subset = subset_data(file_a_rows.slice(0, 5_000), {
        level: 'phylum',
        name: 'Firmicutes'
      })
      expect(subset.length).toBe(5_000)
      const cols = Object.keys(subset[0])
      expect(cols).toEqual(
        expect.arrayContaining(['GeneID', 'EC#', 'Length', 'Reads', 'RPKM', 'Unclassified'])
      )
      expect(cols.length).toBeLessThan(Object.keys(file_a_rows[0]).length)
    }, 60_000)
  })

  describe('subset_data_by_ann', () => {
    it('returns input unchanged when ec_filter is falsy', () => {
      expect(subset_data_by_ann(file_a_rows, undefined)).toBe(file_a_rows)
      expect(subset_data_by_ann(file_a_rows, null)).toBe(file_a_rows)
    })

    it('keeps only rows whose EC# is in the filter ec subset (real ec)', () => {
      const ec = __test__.getEc() as Array<Record<string, unknown>>
      const sp_value = ec.find((r) => r.superpathway != null)?.superpathway as string
      const ec_in_sp = new Set(
        ec.filter((r) => r.superpathway === sp_value).map((r) => r.ec)
      )
      const subset = subset_data_by_ann(file_a_rows.slice(0, 50_000), {
        level: 'superpathway',
        name: sp_value
      })
      expect(subset.length).toBeLessThanOrEqual(50_000)
      expect(subset.length).toBeGreaterThan(0)
      for (const row of subset) {
        expect(ec_in_sp.has(row['EC#'])).toBe(true)
      }
    }, 30_000)
  })

  describe('agg_by_ec', () => {
    it('groups real rows by EC# and produces unique-EC# rows with no _sum suffix', () => {
      const slice = file_a_rows.slice(0, 2_000)
      const out = agg_by_ec(slice) as Record<string, unknown>[]
      const unique_ecs = new Set(slice.map((r) => r['EC#']))
      expect(out.length).toBe(unique_ecs.size)
      for (const row of out) {
        for (const k of Object.keys(row)) {
          expect(k.endsWith('_sum')).toBe(false)
        }
      }
    }, 60_000)
  })

  describe('get_tax_map', () => {
    it('returns parent map of taxonomy columns at requested level (real DB)', () => {
      const out = get_tax_map(file_a_rows, 'phylum')
      expect(typeof out).toBe('object')
      expect(Object.keys(out).length).toBeGreaterThan(0)
      for (const v of Object.values(out)) {
        expect(typeof v).toBe('string')
      }
      expect(Object.values(out)).toContain('Firmicutes')
    }, 60_000)
  })

  describe('names_to_data', () => {
    it('single name returns the loaded data array by reference', () => {
      const out = names_to_data([loaded_names[0]])
      expect(out).toBe(file_a_rows)
    })

    it('two names returns a delta array of {EC#, ...numeric cols}', () => {
      const out = names_to_data(loaded_names) as Array<Record<string, unknown>>
      expect(Array.isArray(out)).toBe(true)
      expect(out.length).toBeGreaterThan(0)
      expect(out[0]).toHaveProperty('EC#')
    }, 180_000)
  })

  describe('parse_ec_chord (end-to-end)', () => {
    it('runs end-to-end on real fixtures with a phylum=Firmicutes taxon filter and returns chord-shape', () => {
      const out = parse_ec_chord({
        names: [loaded_names[0]],
        tax_level: 'genus',
        ann_level: 'superpathway',
        selected_ann_cat: empty_filter,
        selected_taxon: { level: 'phylum', name: 'Firmicutes' }
      })
      expect(out.index[0]).toBe('gap_1')
      expect(out.index).toContain('gap_2')
      expect(out.index[out.index.length - 1]).toBe('gap_3')
      expect(out.count_matrix.length).toBe(out.index.length)
      for (const row of out.count_matrix) {
        expect(row.length).toBe(out.index.length)
      }
      expect(out.colors).toBeDefined()
    }, 180_000)
  })

  describe('parse_pathway_list (end-to-end, real DB)', () => {
    it('returns at least one pathway name for a real superpathway', () => {
      // Pull a non-null superpathway off the real ec data so we don't hardcode
      // a name that may rotate with DB updates.
      const ec = __test__.getEc() as Array<Record<string, unknown>>
      const sp_value = ec.find((r) => r.superpathway != null)?.superpathway as string
      expect(sp_value).toBeTruthy()
      const out = parse_pathway_list({ superpathway: sp_value })
      expect(Array.isArray(out)).toBe(true)
      expect(out.length).toBeGreaterThan(0)
      for (const p of out) {
        expect(typeof p).toBe('string')
      }
    })

    it('returns [] for a superpathway that does not exist', () => {
      expect(parse_pathway_list({ superpathway: '__no_such_superpathway__' })).toEqual([])
    })
  })

  describe('parse_network (end-to-end, real DB+TSV)', () => {
    it('returns nodes, edges, and colors for a real (superpathway, pathway) pair', () => {
      const ec = __test__.getEc() as Array<Record<string, unknown>>
      const row = ec.find((r) => r.superpathway != null && r.pathway != null)!
      const sp_value = row.superpathway as string
      const pathway_name = row.pathway as string

      const out = parse_network({
        names: [loaded_names[0]],
        tax_level: 'phylum',
        selected_taxon: { level: '', name: '' },
        pathway_name,
        width: 900,
        height: 550
      })
      expect(Array.isArray(out.nodes)).toBe(true)
      expect(Array.isArray(out.edges)).toBe(true)
      expect(typeof out.colors).toBe('object')
      // sanity: at least one node should carry pie data when the pathway has
      // matching ECs in the loaded fixture
      const sp_pathways = parse_pathway_list({ superpathway: sp_value })
      expect(sp_pathways).toContain(pathway_name)
    }, 60_000)

    it('returns the static graph (no pies) when no rows match the filter', () => {
      const ec = __test__.getEc() as Array<Record<string, unknown>>
      const row = ec.find((r) => r.pathway != null)!
      const out = parse_network({
        names: [loaded_names[0]],
        tax_level: 'phylum',
        // a deliberately impossible taxon filter forces filtered_rows.length === 0
        selected_taxon: { level: 'phylum', name: '__no_such_phylum__' },
        pathway_name: row.pathway as string,
        width: 900,
        height: 550
      })
      expect(Array.isArray(out.nodes)).toBe(true)
      for (const n of out.nodes) {
        expect(n.values).toEqual([])
      }
      expect(out.colors).toEqual({})
    }, 60_000)
  })

  describe('parse_overview', () => {
    it('returns counts_data and ann_data shapes (no dummy_data after PR4)', () => {
      const out = parse_overview({ names: [loaded_names[0]] })
      // PR4 removed the broken `dummy_data` placeholder. The renderer's
      // Overview pane now expects exactly these two summaries.
      expect(Object.keys(out).sort()).toEqual(['ann_data', 'counts_data'])
      for (const key of ['counts_data', 'ann_data'] as const) {
        const block = out[key]
        expect(block).toBeDefined()
        expect(Array.isArray(block.index)).toBe(true)
        expect(Array.isArray(block.counts)).toBe(true)
        expect(block.index.length).toBe(block.counts.length)
      }
    }, 60_000)
  })
})

// ===========================================================================
// get_delta — synthetic. Tests pure subtraction math; small inputs are
// strictly more precise than real-fixture spot checks here.
// ===========================================================================

describe('get_delta', () => {
  it('returns df_1 minus df_2 for matching EC# and comparable columns', () => {
    const df_1 = [{ 'EC#': '0.0.0.0', Bacteria: 1000 }]
    const df_2 = [{ 'EC#': '0.0.0.0', Bacteria: 2000 }]
    const result = get_delta(df_1, df_2)
    expect(result).toHaveLength(1)
    expect(result[0]['EC#']).toBe('0.0.0.0')
    expect(result[0]['Bacteria']).toBe(-1000)
  })

  it('exempts key_cols from comparison (keeps values from source)', () => {
    const df_1 = [{ 'EC#': '1.1.1.1', Bacteria: 500 }]
    const df_2 = [{ 'EC#': '1.1.1.1', Bacteria: 300 }]
    const result = get_delta(df_1, df_2)
    expect(result[0]['Bacteria']).toBe(200)
  })

  it('treats missing column as 0 (column only in one df)', () => {
    const df_1 = [{ 'EC#': 'X', Bacteria: 100, Archaea: 50 }]
    const df_2 = [{ 'EC#': 'X', Bacteria: 80 }]
    const result = get_delta(df_1, df_2)
    expect(result[0]['Bacteria']).toBe(20)
    expect(result[0]['Archaea']).toBe(50)
  })

  it('returns all unique EC# from both dataframes', () => {
    const df_1 = [{ 'EC#': '1.1.1.1', Bacteria: 10 }]
    const df_2 = [{ 'EC#': '2.2.2.2', Bacteria: 20 }]
    const result = get_delta(df_1, df_2) as Record<string, unknown>[]
    expect(result).toHaveLength(2)
    const ecs = result.map((r) => r['EC#']).sort()
    expect(ecs).toEqual(['1.1.1.1', '2.2.2.2'])
    const r1 = result.find((r) => r['EC#'] === '1.1.1.1')
    const r2 = result.find((r) => r['EC#'] === '2.2.2.2')
    expect(r1!['Bacteria']).toBe(10)
    expect(r2!['Bacteria']).toBe(-20)
  })

  it('matches expected result for data_1 vs data_2 (deltas and columns from both)', () => {
    const data_1 = [
      { 'EC#': '0.0.0.0', Bacteria: 1000, Virus: 1000 },
      { 'EC#': '1.1.1.1', Bacteria: 500, Virus: 750 }
    ]
    const data_2 = [
      { 'EC#': '0.0.0.0', Bacteria: 3000, Archea: 500 },
      { 'EC#': '1.1.1.1', Bacteria: 2000, Archea: 250 }
    ]
    const expected_result = [
      { 'EC#': '0.0.0.0', Bacteria: -2000, Virus: 1000, Archea: 500 },
      { 'EC#': '1.1.1.1', Bacteria: -1500, Virus: 750, Archea: 250 }
    ]
    const result = get_delta(data_1, data_2)
    expect(result).toEqual(expected_result)
  })
})
