import * as dfd from 'danfojs-node'
import fs from 'fs'
import path from 'path'
import _ from 'lodash'
import { parse } from 'csv-parse/sync'

import {
  get_parents_at_level,
  get_superpathway_info,
  // get_pathway_info,
  get_parents_multilevel
} from './db_functions'
import { key_cols, reduce_to_dict } from './utils'
import { parse_ec_data, parse_tax_tree, make_count_vector } from './parse'

// store loaded data in-memory
// cache allows the server to be faster when front-end makes multiple requests
// for the same data set + filters
let data
let data_cache_name
let data_cache_fl
let data_cache_fn
let data_cache

// store loaded ec annotations in-memory
let ec
let ec_cache
// let ec_cache_name // ec doesn't have a name.. yet
let ec_cache_fl
let ec_cache_fn

const test_data_paths = [
  '../../resources/example_data/test_rpkm_1.tsv',
  '../../resources/example_data/test_rpkm_2.tsv'
]

const get_fname = (f_path) => {
  const t = f_path.split('/')
  return t[t.length - 1].substring(-4)
}

const add_initial_data = () => {
  ec = get_superpathway_info()
}

const initialize = () => {
  // TODO: check for database

  add_initial_data()
}

const add_data = ({ name: new_name, data: new_data, test = false }) => {
  let to_add
  if (test) {
    to_add = test_data_paths.map((e) => [
      get_fname(e),
      fs.readFileSync(path.join(__dirname, e), 'utf8')
    ])
  } else {
    to_add = [[new_name, new_data]]
  }

  const parsed_data = to_add.map((e) => [
    e[0],
    parse(e[1], {
      delimiter: '\t',
      columns: true,
      skip_empty_lines: true
    })
  ])

  data = { ...data, ...Object.fromEntries(parsed_data) }
}

// when making a request, always supply the filter parameter
// if it doesn't actually exist, put the filter_name as '' or a falsy value
const subset_data = (name, { level, name: filter_name }) => {
  if (!filter_name) return data

  if (name === data_cache_name && level == data_cache_fl && filter_name == data_cache_fn) {
    return data_cache
  } else {
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
    const f_data = ec[name].map((e) => _.pick(e, good_keys))
    // save to cache

    ec_cache = f_data
    ec_cache_fl = level
    ec_cache_fn = filter_name

    return f_data
  }
}

const subset_ec = ({ level, name }) => {
  if (level == ec_cache_fl && name == ec_cache_fn) {
    return ec_cache
  } else {
    const f_data = ec.filter((e) => e[level] === name)

    // save to cache
    ec_cache = f_data
    ec_cache_fl = level
    ec_cache_fn = name

    return f_data
  }
}

const agg_by_ec = (data) => {
  const df = new dfd.DataFrame(data)

  const ops = Object.fromEntries(
    df.columns.filter((e) => !key_cols.includes(e)).map((e) => [e, 'sum'])
  )
  const agg_df = df.groupby(['EC#']).agg(ops)
  console.log(agg_df)
  agg_df.rename(
    Object.fromEntries(
      agg_df.columns.filter((e) => e.endsWith('_sum')).map((e) => [e, e.substring(0, e.length-4)])
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
  return reduce_to_dict(
    subset_ec(filter).map((e) => [
      e['ec'],
      level === 'pathway' ? e['pathway_name'] : e['superpathway']
    ])
  )
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
const parse_ec_chord = (
  names: string[],
  tax_level: string,
  ann_level: string,
  selected_ann_cat: { level: string; name: string },
  selected_taxon: { level: string; name: string }
) => {
  // if in comparison mode, get the delta first
  const ec_map = get_ec_map(selected_ann_cat, ann_level)
  const raw_data = names_to_data(names)

  const agg_data = agg_by_ec(subset_data(raw_data, selected_taxon))
  return parse_ec_data({
    data: raw_data,
    tax_map: get_tax_map(agg_data, tax_level), // tax_map
    ec_map
  })
}

// const parsed_data_to_df = (parsed_data) => {
//   const {count_matrix, index} = parsed_data

//   const tax_range = _.range(1, index.indexOf('gap_1'))
//   const ann_range = _.range(index.indexOf('gap_1') + 1, index.length - 1)

//   const new_matrix = ann_range.map(e => {
//     const tmp = count_matrix[e]
//     return tax_range.map(e2 => tmp[e2])
//   })

//   return new dfd.DataFrame(new_matrix, {
//     index: ann_range.map(e => index[e]),
//     columns: tax_range.map(e => index[e]),
//   })
// }

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
const parse_krona = (names: string[], tax_rank, selected_taxon) => {
  const data = subset_data(names_to_data(names), selected_taxon)
  const tax_terms = Object.keys(data[0]).filter((e) => !key_cols.includes(e))
  const levels = _.uniq([tax_rank, 'genus', 'species'])
  const tax_tree = get_parents_multilevel(tax_terms, levels)
  return parse_tax_tree(data, tax_tree, levels)
}

export { parse_ec_chord, parse_krona, initialize, add_data, get_delta }
