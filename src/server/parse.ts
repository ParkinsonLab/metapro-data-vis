import { get_color, get_sub_color, key_cols, sum } from './utils'
import _ from 'lodash'
// file for the data parser
// cols from ec_rpkm which don't countain counts

const sort_by_category = (
  a: string,
  b: string,
  get_cat_idx: (name: string) => number
): number => {
  const m_a = get_cat_idx(a)
  const m_b = get_cat_idx(b)
  const v_a = m_a === m_b ? a : m_a
  const v_b = m_a === m_b ? b : m_b
  if (v_a < v_b) return -1
  if (v_a > v_b) return 1
  return 0
}

const make_inner_count_matrix = (
  data: Array<object>,
  matrix_index: string[]
): number[][] => {
  const add_to_count_map = (
    acc: number[][],
    species: string,
    annotation: string,
    value: number
  ): void => {
    const species_index = matrix_index.indexOf(species)
    const annotation_index = matrix_index.indexOf(annotation)
    if (species_index >= 0 && annotation_index >= 0) {
      acc[species_index][annotation_index] += Number(value)
      acc[annotation_index][species_index] += Number(value)
    }
  }

  const rows = data as Array<Record<string, string | number>>
  const val_cols = Object.keys(rows[0]).filter((e) => !key_cols.includes(e))
  return rows.reduce(
    (acc: number[][], row) => {
      const ec_key = String(row['EC#'])
      for (const key of val_cols) {
        const val = Number(row[key])
        if (val > 0) add_to_count_map(acc, key, ec_key, val)
      }
      return acc
    },
    Array.from({ length: matrix_index.length }, () =>
      Array(matrix_index.length).fill(0)
    )
  )
}

const primary_ann_cat = (ec_map: Record<string, string[]>, ec: string): string =>
  ec_map[ec]?.[0] ?? ''

const parse_graph_data = ({
  data,
  ec_map,
  tax_map
}: {
  data: Array<object>
  ec_map: Record<string, string[]>
  tax_map: Record<string, string>
}) => {
  const tax_cats = _.uniq(_.sortBy(Object.values(tax_map)))
  const all_taxa = _.uniq(Object.keys(tax_map)).sort((a, b) =>
    sort_by_category(a, b, (name) => tax_cats.indexOf(tax_map[name]))
  )

  const annotation_cats = _.sortBy(
    _.uniq(Object.values(ec_map).reduce((acc, vals) => [...acc, ...vals], [] as string[]))
  )
  const all_annotations = _.uniq(Object.keys(ec_map)).sort((a, b) =>
    sort_by_category(a, b, (name) => annotation_cats.indexOf(primary_ann_cat(ec_map, name)))
  )

  const outer_matrix_index = ['gap_1', ...annotation_cats, 'gap_2', ...tax_cats, 'gap_3']

  const inner_matrix_index = ['gap_1', ...all_annotations, 'gap_2', ...all_taxa, 'gap_3']
  const inner_count_matrix = make_inner_count_matrix(data, inner_matrix_index)

  const idx_to_keep = inner_count_matrix.reduce((acc: number[], row, i) => {
    if (sum(row) > 0) acc.push(i)
    return acc
  }, [])
  const trimmed_inner_count_matrix = idx_to_keep.map((i) =>
    idx_to_keep.map((j) => inner_count_matrix[i][j])
  )
  const trimmed_inner_matrix_idx = idx_to_keep.map((i) => inner_matrix_index[i])

  const cat_colors = Object.fromEntries([
    ...annotation_cats.map((e, i, arr) => [e, get_color(i, arr.length)]),
    ...tax_cats.map((e, i, arr) => [e, get_color(i, arr.length)])
  ])
  const sub_colors = Object.fromEntries([
    ...all_annotations.map((e) => [
      e,
      get_sub_color(cat_colors[primary_ann_cat(ec_map, e)], e)
    ]),
    ...all_taxa.map((e) => [e, get_sub_color(cat_colors[tax_map[e]], e)])
  ])
  const colors = { ...sub_colors, ...cat_colors }

  return {
    inner_count_matrix: trimmed_inner_count_matrix,
    inner_matrix_index: trimmed_inner_matrix_idx,
    outer_matrix_index,
    colors,
    tax_map
  }
}

// makes a count matrix from precalculated parameters and name mappers
// refactored out because we need to call it at least twice to make the inner and outer arcs
const make_count_matrix = (data, matrix_index, tax_map, ann_map) => {
  const add_to_count_map = (
    acc: number[][],
    species: string,
    annotations: string[],
    value: number
  ): void => {
    // if either are missing, just skip this row
    if (!(species && annotations)) {
      return
    }
    const species_index = matrix_index.indexOf(tax_map ? tax_map[species] : species)
    const annotation_idc = annotations.map((e) => matrix_index.indexOf(e))
    if (species_index >= 0) {
      for (const annotation_index of annotation_idc) {
        if (annotation_index >= 0) {
          acc[species_index][annotation_index] += Number(value)
          acc[annotation_index][species_index] += Number(value)
        }
      }
    }
  }

  const val_cols = Object.keys(data[0]).filter((e) => !key_cols.includes(e))
  const count_matrix = data.reduce(
    (acc: number[][], row: Record<string, string | number>) => {
      const ec_key = row['EC#']
      for (const key of val_cols) {
        const val = Number(row[key])
        if (val > 0) {
          add_to_count_map(acc, key, ann_map[ec_key], val)
        }
      }
      return acc
    },
    Array.from({ length: matrix_index.length }, () => Array(matrix_index.length).fill(0))
  )
  return count_matrix
}

const add_filler_value = (count_matrix, index) => {
  //add filler
  const filler_nodes = ['gap_1', 'gap_2', 'gap_3']
  const flat_sum = sum(count_matrix.flat())
  filler_nodes.forEach((name, idx) => {
    const i = index.indexOf(name)
    const div = idx === 1 ? 2 : 4
    count_matrix[i][i] = flat_sum / div
  })

  return count_matrix
}

const parse_ec_data = ({
  data,
  ec_map,
  tax_map
}: {
  data: Array<object>
  ec_map: Record<string, string[]> // ec map is not 1:1
  tax_map: Record<string, string>
}) => {
  // maps taxonomic names to domains

  const tax_cats = _.uniq(_.sortBy(Object.values(tax_map)))
  const annotation_cats = _.sortBy(
    _.uniq(Object.values(ec_map).reduce((acc, e) => [...acc, ...e], []))
  )

  const index = ['gap_1'].concat(
    annotation_cats, // super pathways
    ['gap_2'],
    tax_cats, // domains
    ['gap_3']
  )
  const count_matrix = add_filler_value(make_count_matrix(data, index, tax_map, ec_map), index)
  const colors = Object.fromEntries([
    ...annotation_cats.map((e, i, arr) => [e, get_color(i, arr.length)]),
    ...tax_cats.map((e, i, arr) => [e, get_color(i, arr.length)])
  ])

  return {
    count_matrix,
    index,
    colors,
    tax_map,
    ann_map: ec_map
  }
}

const make_count_vector = (data: Array<object>, tax_map: object) => {
  // a simplified count matrix that just tallies the total RPKM mapped to each taxonomic category
  const tax_cats = _.uniq(_.sortBy(Object.values(tax_map)))
  const all_taxa = _.uniq(Object.keys(tax_map))
  const counts = Object.fromEntries(tax_cats.map((e) => [e, []]))
  for (const row of data) {
    for (const taxon of all_taxa) {
      const cat = tax_map[taxon]
      const val = Number(row[taxon])
      if (cat && val > 0) counts[cat].push(val)
    }
  }
  return {
    index: tax_cats,
    counts: tax_cats.map((e) => sum(counts[e]))
  }
}

// similar to make count vector but for annotations (i.e. row-wise sum)
const make_ann_vector = (data, ann_map) => {
  // a simplified count matrix that just tallies the total RPKM mapped to each taxonomic category
  const all_taxa = Object.keys(data[0]).filter((e) => !key_cols.includes(e))
  const res = Object.fromEntries(Object.values(ann_map).map((e) => [e, 0]))
  const tmp = data.map((e) => [
    e['EC#'],
    sum(Object.values(_.pick(e, all_taxa)).map((e) => Number(e)))
  ])
  for (const [ec, val] of tmp) {
    res[ann_map[ec]] += val
  }
  const index = Object.keys(res)
  return {
    index: index,
    counts: index.map((e) => res[e])
  }
}

const group_tax_tree_at_level = (tax_tree, level) => {
  // we can assume that theses share a common ancestor at the previous level
  const keys = tax_tree.map((e) => (e[level] ? e[level] : `Unclassified ${e.id}`))
  const groups = tax_tree.reduce(
    (acc, e, i) => {
      acc[keys[i]].push(e)
      return acc
    },
    Object.fromEntries(_.uniq(keys).map((e) => [e, []]))
  )

  return Object.entries(groups).map(([k, v]) => ({
    subset_name: k,
    subset: v
  })) // gets all elements of tax_tree that belongs to each group
}

const parse_tax_tree_recursive = (data, tax_tree, levels, name, total) => {
  const species_level = levels.length === 0
  const no_children = tax_tree.length === 1 && !tax_tree[0][levels[1]]
  if (species_level || no_children) {
    // only one element should make it to the last level
    const id = tax_tree[0].id
    const label = species_level ? id : `U_${id}`
    return {
      id: id,
      label: label, // generally should be species
      value: data[id],
      percentage: data[id] / total
    }
  } else {
    const tax_tree_subsets = group_tax_tree_at_level(tax_tree, levels[0])
    const children = tax_tree_subsets.map(({ subset_name, subset }) => {
      return parse_tax_tree_recursive(data, subset, levels.slice(1), subset_name, total)
    })
    return {
      id: name,
      label: name,
      children,
      percentage: sum(children.map((e) => e.percentage))
    }
  }
}

const parse_tax_tree = (data, tax_tree, levels) => {
  // this makes use the 1D matrix function but do not aggregate to taxonomic categories
  // by using self_map instead of a real tax_map so each entry is its own category
  const self_map = Object.fromEntries(tax_tree.map((e) => [e.id, e.id]))
  const { index: counts_idx, counts } = make_count_vector(data, self_map)
  const parsed_data = Object.fromEntries(counts_idx.map((e, i) => [e, counts[i]]))
  const total = sum(Object.values(parsed_data))
  return parse_tax_tree_recursive(parsed_data, tax_tree, levels, 'root', total)
}

export {
  parse_ec_data,
  parse_graph_data,
  make_inner_count_matrix,
  sort_by_category,
  make_count_vector,
  make_ann_vector,
  parse_tax_tree
}
