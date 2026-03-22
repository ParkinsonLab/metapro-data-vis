import * as dfd from 'danfojs-node'
import fs from 'fs'
import path from 'path'
import _ from 'lodash'
import { parse } from 'csv-parse/sync'

import {
  get_parents_at_level,
  get_superpathway_info,
  get_pathway_info,
  get_parents_multilevel,
  check_db,
  get_name_from_id
} from './db_functions'
import { key_cols, reduce_to_dict, empty_filter, get_color } from './utils'
import { parse_ec_data, parse_tax_tree, make_count_vector, make_ann_vector } from './parse'

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
}

const add_data = ({ name, data: raw_data }) => {
  console.log('add_data')
  const parsed_data = parse(raw_data, {
    delimiter: '\t',
    columns: (header) => {
      header.map((e) => (key_cols.includes(e) ? e : get_name_from_id(e)))
    },
    skip_empty_lines: true
  }).map((item) => ({
    ...item,
    'EC#': item['EC#'].substring(3)
  }))
  console.log(parsed_data.slice(0, 10))
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
const subset_data = (name, { level, name: filter_name }) => {
  if (!(level && filter_name)) return data

  // subset
  const raw_data = ec[name]
  const parent_map = get_parents_at_level(
    Object.keys(raw_data[0]).filter((e) => key_cols.includes(e)),
    level
  )
  const good_keys = [
    ...key_cols,
    ...Object.keys(parent_map).filter((e) => parent_map[e] === filter_name)
  ]
  return data[name].map((e) => _.pick(e, good_keys))
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
  console.log(df.head(10))
  const agg_df = df.groupby(['EC#']).agg(ops)
  agg_df.rename(
    Object.fromEntries(
      agg_df.columns.filter((e) => e.endsWith('_sum')).map((e) => [e, e.substring(0, e.length - 4)])
    ),
    { inplace: true }
  )
  return dfd.toJSON(agg_df, { format: 'row' })
}

const get_tax_map = (data, level) => {
  return get_parents_at_level(
    _.uniq(Object.keys(data[0]).filter((e) => key_cols.includes(e))),
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
    raw_data = get_delta(data[names[0]], data[names[2]])
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
      new_col = merge_df[col].sub(merge_df[alt_col])
    } else {
      new_col = merge_df[col]
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

const subset_parsed_data = (data_matrix, data_matrix_index, annotation_checker) => {
  // rows only for annotations that pass the checker
  const ann_idx = data_matrix_index.filter((e) => annotation_checker(e))
  const tax_idx_start = data_matrix_index.indexOf('gap_2') + 1
  const tax_idx_end = data_matrix_index.indexOf('gap_3')
  const tax_idx = data_matrix_index.slice(tax_idx_start, tax_idx_end)
  const t_1 = data_matrix.filter((_, i) => annotation_checker(data_matrix_index[i]))
  const t_2 = t_1.map((e) => e.slice(tax_idx_start, tax_idx_end))
  return {
    data: t_2,
    ann_idx, // 1st dimension index
    tax_idx // 2nd dimension index
  }
}

const parse_network = ({ names, tax_level, selected_taxon, pathway_name, width, height }) => {
  const { count_matrix, index, colors, ann_map } = parse_ec_chord({
    names,
    tax_level,
    ann_level: 'ec',
    selected_taxon,
    selected_ann_cat: { level: 'pathway', name: pathway_name }
  })
  const { data, ann_idx, tax_idx } = subset_parsed_data(
    count_matrix,
    index,
    (e) => ann_map[e] === pathway_name
  )

  const network_data = get_pathway_info(pathway_name)
  const new_nodes = network_data.nodes.map((e) => {
    return {
      ...e,
      x: (e.y / 1100) * width - width / 2 + 100,
      y: (e.x / 1000) * height - height / 2,
      values: ann_idx.includes(e.label)
        ? data[ann_idx.indexOf(e.label)].map((e, i) => ({
            id: tax_idx[i],
            value: e
          }))
        : []
    }
  })

  const new_edges = network_data.edges.map((e) => ({
    source: _.find(new_nodes, (e2) => e2.id === e.source),
    target: _.find(new_nodes, (e2) => e2.id === e.target)
  }))

  const to_return = {
    nodes: new_nodes,
    edges: new_edges,
    colors: colors
  }
  return to_return
}

// the overview always happens at the phylum and superpathway level
const parse_overview = ({ names }) => {
  const data_subset = subset_data(names_to_data(names), empty_filter)
  const tax_map = get_tax_map(data_subset, 'phylum')
  const ann_map = get_ec_map(empty_filter, 'superpathway')
  const counts_data = make_count_vector(data_subset, tax_map)
  const ann_data = make_ann_vector(data_subset, ann_map)
  const dummy_data = {
    index: ['g1', 'g2', 'g3', 'g4', 'g5'],
    counts: [5, 17, 22, 8, 11],
    colors: Array(5).map((_, i) => get_color(i, 5))
  }
  return {
    counts_data,
    ann_data,
    dummy_data
  }
}

export {
  parse_ec_chord,
  parse_krona,
  initialize,
  add_data,
  add_test_data,
  get_delta,
  parse_counts,
  parse_network,
  parse_overview
}
