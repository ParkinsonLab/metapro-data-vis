import * as dfd from 'danfojs-node'
import fs from 'fs'
import path from 'path'
import _ from 'lodash'
import { parse, type CastingContext } from 'csv-parse/sync'

import {
  get_parents_at_level,
  get_superpathway_info,
  get_pathway_info,
  get_pathways_in_superpathway,
  get_parents_multilevel,
  check_db,
  get_name_from_id
} from './db_functions'
import { key_cols, reduce_to_dict, empty_filter, get_color } from './utils'
import {
  parse_ec_data,
  parse_graph_data,
  parse_tax_tree,
  make_count_vector,
  make_ann_vector
} from './parse'

// store loaded data and ec in-memory
let data = {}
let ec

const test_data_paths = [
  '../../resources/example_data/test_rpkm_1.tsv',
  '../../resources/example_data/test_rpkm_2.tsv'
]

const get_fname = (f_path) => {
  const t = f_path.split('/')
  return t[t.length - 1].substring(-4)
}

const initialize = () => {
  // TODO: check for database
  console.log('initialize')
  if (!check_db()) {
    // TODO: download the database
    return 3
  }
  ec = get_superpathway_info()
  return 0
}

const coerce_cell_to_float = (raw: string | undefined): number | null => {
  if (raw == null) return null
  const s = String(raw).trim()
  if (s === '') return null
  if (/^(nan|na|null|none)$/i.test(s)) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

const normalize_ec_value = (value: string): string => {
  const s = value.trim()
  if (s === '' || /^none$/i.test(s)) return '0.0.0.0'
  const body = /^EC:/i.test(s) ? s.slice(3).trim() : s
  if (body === '' || /^none$/i.test(body)) return '0.0.0.0'
  return body
}

/** Per-field cast during parse: one pass, no second row map or per-row object spread. */
const add_data_field_cast = (value: string, context: CastingContext): string | number | null => {
  if (context.header) return value
  const col = context.column
  if (col === 'GeneID') return value
  if (col === 'EC#') return normalize_ec_value(value)
  return coerce_cell_to_float(value)
}

const add_data = ({ name, data: raw_data }) => {
  console.log('add_data')
  const missing_tax_ids = new Set<string | number>()
  const parsed_data = parse<Record<string, string | number | null>>(raw_data, {
    delimiter: '\t',
    columns: (header) =>
      header.map((e) => (key_cols.includes(e) ? e : get_name_from_id(e, missing_tax_ids))),
    cast: add_data_field_cast,
    cast_date: false,
    skip_empty_lines: true
  })
  if (missing_tax_ids.size > 0) {
    console.warn(
      `[add_data:${name}] ${missing_tax_ids.size} tax_id(s) not found in name db; using raw ids as fallback`
    )
  }
  data = { ...data, [name]: parsed_data }
  return name
}

const add_test_data = () => {
  console.log('add_test_data')
  const to_add = test_data_paths.map((e) => [
    get_fname(e),
    fs.readFileSync(path.join(__dirname, e), 'utf8')
  ])
  for (const [name, data] of to_add) {
    add_data({ name, data })
  }
  return to_add.map((e) => e[0])
}

// when making a request, always supply the filter parameter
// if it doesn't actually exist, put the filter_name as '' or a falsy value
const subset_data = (raw_data, { level, name: filter_name }) => {
  if (!(level && filter_name)) return raw_data

  // subset
  const parent_map = get_parents_at_level(
    Object.keys(raw_data[0]).filter((e) => !key_cols.includes(e)),
    level
  )
  const good_keys = [
    ...key_cols,
    ...Object.keys(parent_map).filter((e) => parent_map[e] === filter_name)
  ]
  return raw_data.map((e) => _.pick(e, good_keys))
}

const subset_ec = ({ level, name }) => {
  if (!(level && name)) return ec
  return ec.filter((e) => e[level] === name)
}

const subset_data_by_ann = (data, ec_filter) => {
  if (!ec_filter) return data
  const ec_subset = subset_ec(ec_filter).map((e) => e['ec'])
  return data.filter((e) => ec_subset.includes(e['EC#']))
}

const agg_by_ec = (data) => {
  const df = new dfd.DataFrame(data)

  const ops = Object.fromEntries(
    df.columns.filter((e) => !key_cols.includes(e)).map((e) => [e, 'sum'])
  )
  const agg_df = df.groupby(['EC#']).agg(ops)
  agg_df.rename(
    Object.fromEntries(
      agg_df.columns.filter((e) => e.endsWith('_sum')).map((e) => [e, e.substring(0, e.length - 4)])
    ),
    { inplace: true }
  )
  return dfd.toJSON(agg_df, { format: 'column' })
}

/** `data` must be one consistent row matrix: either rows from a single loaded file or rows already merged from multiple files (same columns on every row). */
const get_tax_map = (data, level) => {
  return get_parents_at_level(
    _.uniq(Object.keys(data[0]).filter((e) => !key_cols.includes(e))),
    level
  )
}

const get_ec_map = (filter, level) => {
  return reduce_to_dict(subset_ec(filter).map((e) => [e['ec'], e[level]]))
}

const names_to_data = (names: string[]) => {
  let raw_data
  if (!names[1]) {
    raw_data = data[names[0]]
  } else {
    raw_data = get_delta(data[names[0]], data[names[1]])
  }
  return raw_data
}

// parses loaded data into a data object for the chord diagram with EC annotations
const parse_ec_chord = ({
  names,
  tax_level,
  ann_level,
  selected_ann_cat,
  selected_taxon
}: {
  names: string[]
  tax_level: string
  ann_level: string
  selected_ann_cat: { level: string; name: string }
  selected_taxon: { level: string; name: string }
}) => {
  console.log('parse_ec_chord')
  // if in comparison mode, get the delta first
  const ec_map = get_ec_map(selected_ann_cat, ann_level)
  const raw_data = names_to_data(names)

  const agg_data = agg_by_ec(
    subset_data_by_ann(subset_data(raw_data, selected_taxon), selected_ann_cat)
  )
  return parse_ec_data({
    data: raw_data,
    tax_map: get_tax_map(agg_data, tax_level), // tax_map
    ec_map
  })
}

const parse_graph = ({
  names,
  tax_level,
  ann_level,
  selected_ann_cat,
  selected_taxon
}: {
  names: string[]
  tax_level: string
  ann_level: string
  selected_ann_cat: { level: string; name: string }
  selected_taxon: { level: string; name: string }
}) => {
  const raw_data = names_to_data(names)
  const filtered = subset_data_by_ann(
    subset_data(raw_data, selected_taxon),
    selected_ann_cat
  )
  const agg_data = agg_by_ec(filtered) as Array<Record<string, string | number>>
  const ec_map = get_ec_map(selected_ann_cat, ann_level)
  const tax_map = get_tax_map(agg_data, tax_level)
  return parse_graph_data({ data: agg_data, ec_map, tax_map })
}

/**
 * Returns the difference (df_1 - df_2) for matching rows and columns.
 * EC# is the row identifier. key_cols are exempt from comparison.
 * Missing rows/columns are treated as 0.
 */
const get_delta = (data_1: object[], data_2: object[]) => {
  const df_1 = new dfd.DataFrame(agg_by_ec(data_1))
  const df_2 = new dfd.DataFrame(agg_by_ec(data_2))

  const merge_df = dfd.merge({ left: df_1, right: df_2, on: ['EC#'], how: 'outer' }).fillNa(0)

  const val_cols = _.uniq(df_1.columns.concat(df_2.columns)).filter((e) => !key_cols.includes(e))

  const res = merge_df.loc({ columns: ['EC#'] })
  for (const col of val_cols) {
    const alt_col = `${col}_1`
    let new_col
    if (merge_df.columns.includes(alt_col)) {
      // Ensure both columns are numeric before subtraction
      const col_numeric = merge_df.column(col).asType('float32')
      const alt_col_numeric = merge_df.column(alt_col).asType('float32')
      new_col = col_numeric.sub(alt_col_numeric)
    } else {
      // Ensure the column is numeric
      new_col = merge_df.column(col).asType('float32')
    }
    res.addColumn(col, new_col, { inplace: true })
  }
  return dfd.toJSON(res, { format: 'column' })
}

// this is the function to call when data is first uploaded
// it is broader than parse_data
const parse_krona = ({ names, tax_rank, selected_taxon }) => {
  const data_subset = subset_data(names_to_data(names), selected_taxon)
  const tax_terms = Object.keys(data_subset[0]).filter((e) => !key_cols.includes(e))
  const levels = _.uniq([tax_rank, 'genus', 'species'])
  const tax_tree = get_parents_multilevel(tax_terms, levels)
  return parse_tax_tree(data_subset, tax_tree, levels)
}

// this is meant for the preview
const parse_counts = ({ names, tax_rank, selected_taxon, selected_ann_cat }) => {
  const data_subset = subset_data_by_ann(
    subset_data(names_to_data(names), selected_taxon),
    selected_ann_cat
  )

  const tax_map = get_tax_map(data_subset, tax_rank)
  return make_count_vector(data_subset, tax_map)
}

/**
 * Build the per-pathway network view.
 *
 * Renders the static pathway graph (from `pathway_nodes` / `pathway_edges`) and
 * decorates each enzyme node with a small tax-distribution pie computed from
 * the loaded data (filtered to ECs in this pathway and the user's tax filter).
 *
 * Earlier versions delegated tax aggregation to `parse_ec_chord`, but the
 * `ann_map` it returns at `ann_level: 'ec'` is `ec → ec` (not `ec → pathway`),
 * so the row filter never matched and the pie data was always empty. We now
 * compute the per-EC tax breakdown directly from the filtered data, which is
 * also faster (no symmetric chord matrix is built).
 */
const parse_network = ({
  names,
  tax_level,
  selected_taxon,
  pathway_name,
  width,
  height
}: {
  names: string[]
  tax_level: string
  selected_taxon: { level: string; name: string }
  pathway_name: string
  width: number
  height: number
}) => {
  console.log('parse_network')

  const network_data = get_pathway_info(pathway_name)
  const placed_nodes = network_data.nodes.map((node) => ({
    ...node,
    // The pathway-graph layout was authored with x/y swapped relative to our
    // SVG axes; we flip and rescale into the renderer's viewBox here so the
    // renderer can stay generic.
    x: (node.y / 1100) * width - width / 2 + 100,
    y: (node.x / 1000) * height - height / 2
  }))

  const filtered_rows = subset_data_by_ann(
    subset_data(names_to_data(names), selected_taxon),
    { level: 'pathway', name: pathway_name }
  )

  let tax_cats: string[] = []
  let colors: Record<string, string> = {}
  const ec_to_pie = new Map<string, number[]>()

  // `subset_data` may strip every taxonomy column when the taxon filter has
  // no matches; `agg_by_ec` then crashes inside danfojs because it has no
  // value columns to sum. Skip aggregation when nothing's left to aggregate.
  const has_value_cols =
    filtered_rows.length > 0 &&
    filtered_rows[0] &&
    Object.keys(filtered_rows[0]).some((k) => !key_cols.includes(k))

  if (has_value_cols) {
    const agg_rows = agg_by_ec(filtered_rows) as Array<Record<string, number | string>>
    if (agg_rows.length > 0) {
      const tax_columns = Object.keys(agg_rows[0]).filter((c) => !key_cols.includes(c))
      const tax_map = get_parents_at_level(tax_columns, tax_level)
      tax_cats = _.uniq(_.sortBy(Object.values(tax_map))) as string[]
      colors = Object.fromEntries(tax_cats.map((cat, i) => [cat, get_color(i, tax_cats.length)]))

      for (const row of agg_rows) {
        const ec = String(row['EC#'])
        const pie = tax_cats.map(() => 0)
        for (const taxon of tax_columns) {
          const cat = tax_map[taxon]
          if (!cat) continue
          const pos = tax_cats.indexOf(cat)
          if (pos < 0) continue
          const value = Number(row[taxon])
          if (Number.isFinite(value)) pie[pos] += value
        }
        ec_to_pie.set(ec, pie)
      }
    }
  }

  const new_nodes = placed_nodes.map((node) => {
    const pie = ec_to_pie.get(node.label)
    return {
      ...node,
      values: pie ? tax_cats.map((cat, i) => ({ id: cat, value: pie[i] })) : []
    }
  })

  const new_edges = network_data.edges.map((edge) => ({
    source: _.find(new_nodes, (n) => n.id === edge.source),
    target: _.find(new_nodes, (n) => n.id === edge.target)
  }))

  return { nodes: new_nodes, edges: new_edges, colors }
}

/**
 * Return the names of every pathway under a given superpathway.
 *
 * The renderer uses this to populate the clickable pathway grid in the
 * Network pane before any expensive per-pathway layout is computed.
 */
const parse_pathway_list = ({
  superpathway,
  selected_ann_cat,
}: {
  superpathway?: string
  selected_ann_cat?: { level?: string; name?: string }
}): string[] => {
  const sp =
    superpathway?.trim() ||
    (selected_ann_cat?.name?.trim() ?? '')
  if (!sp) return []
  return get_pathways_in_superpathway(sp).map((p) => p.name)
}

// the overview always happens at the phylum and superpathway level
const parse_overview = ({ names }) => {
  const data_subset = subset_data(names_to_data(names), empty_filter)
  const tax_map = get_tax_map(data_subset, 'phylum')
  const ann_map = get_ec_map(empty_filter, 'superpathway')
  const counts_data = make_count_vector(data_subset, tax_map)
  const ann_data = make_ann_vector(data_subset, ann_map)
  return {
    counts_data,
    ann_data
  }
}

// In-process debug harness. Only runs when explicitly enabled so importers
// (e.g. unit tests, the renderer process via IPC) don't pay the ~60s cost
// or mask errors from individual functions.
if (process.env.RUN_HARNESS === '1') {
  initialize()
  add_test_data()
  console.log(
    parse_ec_chord({
      names: ['test_rpkm_1.tsv', 'test_rpkm_2.tsv'],
      tax_level: 'genus',
      ann_level: 'superpathway',
      selected_ann_cat: empty_filter,
      selected_taxon: { level: 'phylum', name: 'Firmicutes' }
    })
  )
  console.log('complete')
}

const __test__ = {
  setData: (next: Record<string, unknown>): void => {
    data = next
  },
  setEc: (next: unknown): void => {
    ec = next
  },
  getData: (): Record<string, unknown> => data,
  getEc: (): unknown => ec,
  reset: (): void => {
    data = {}
    ec = undefined
  }
}

export {
  parse_ec_chord,
  parse_graph,
  parse_krona,
  initialize,
  add_data,
  add_test_data,
  get_delta,
  parse_counts,
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
}
