import { describe, it, expect } from 'vitest'
import { parse_ec_chord, add_test_data, initialize } from '../main/data_functions'

describe('chord_api', () => {
  // Real fixture pipeline takes ~20s on the full TSVs; default 5s timeout is too low.
  it(
    'completes',
    () => {
      initialize()
      const names = add_test_data()
      const default_settings = {
        selected_ann_cat: {},
        selected_taxon: {},
        selected_pathway: '',
        selected_annotations: [],
        tax_rank: 'phylum',
        ann_rank: 'superpathway'
      }
      const res = parse_ec_chord({
        names,
        tax_level: default_settings.tax_rank,
        ann_level: default_settings.ann_rank,
        selected_ann_cat: default_settings.selected_ann_cat,
        selected_taxon: default_settings.selected_taxon
      })
      expect(Object.keys(res)).toContain('count_matrix')
    },
    60_000
  )
})
