import { get_color, get_sub_color } from './util'
import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import * as d3 from 'd3'

// file for the data parser
// cols from ec_rpkm which don't countain counts
const key_cols = ['EC#', 'GeneID', 'Length', 'Reads', 'RPKM']

// // standardized names for taxonomy at the domain level
// const tax_domains = {
//     "bacteria": "Bacteria",
//     "firmicutes": "Firmicutes",
//     "actino": "Actinobacteria",
//     "proteo": "Proteobacteria",
//     "virus": "Viruses",
//     "archaea": "Archaea",
// }

// // How species map to domains. Will need to fill this out more
// const domain_map = {
//     "Methanosphaera stadtmanae": tax_domains.firmicutes,
//     "Methanobrevibacter smithii": tax_domains.archaea,
// }

// helper function that performs two-level sorting, category first
const sort_by_category = (a, b, get_cat_idx: Function) => {
  // get_cat_idx(a) returns numerical index of the category a belongs to
  // sort by category first, then alphabetically if equal
  const m_a = get_cat_idx(a)
  const m_b = get_cat_idx(b)
  const v_a = m_a === m_b ? a : m_a
  const v_b = m_a === m_b ? b : m_b
  // TODO: if equal, sort regularly
  if (v_a < v_b) return -1
  if (v_a > v_b) return 1
  return 0
}

// makes a count matrix from precalculated parameters and name mappers
// refactored out because we need to call it at least twice to make the inner and outer arcs
const make_count_matrix = (data, matrix_index, tax_map = null, ann_map = null) => {
  const add_to_count_map = (acc: any, species: string, annotation: string, value: number) => {
    const species_index = matrix_index.indexOf(tax_map ? tax_map[species] : species)
    const annotation_index = matrix_index.indexOf(ann_map ? ann_map[annotation] : annotation)
    if (species_index >= 0 && annotation_index >= 0) {
      acc[species_index][annotation_index] += Number(value)
      acc[annotation_index][species_index] += Number(value)
    }
  }

  const count_matrix = data.reduce(
    (acc: any, row: any) => {
      const ec_key = row['EC#']
      Object.keys(row).forEach((key) => {
        if (!key_cols.includes(key) && row[key] > 0) {
          add_to_count_map(acc, key, ec_key, row[key])
        }
      })
      return acc
    },
    Array.from({ length: matrix_index.length }, () => Array(matrix_index.length).fill(0))
  )

  //add filler
  const filler_nodes = ['gap_1', 'gap_2', 'gap_3']
  const flat_sum = d3.sum(count_matrix.flat())
  filler_nodes.forEach((name, idx) => {
    const i = matrix_index.indexOf(name)
    const div = idx === 1 ? 2 : 4
    count_matrix[i][i] = flat_sum / div
  })

  return count_matrix
}

const parse_data_callback = (
  data: Array<object>,
  ec_map: Record<string, string>,
  tax_map: Record<string, string>
) => {
  // maps taxonomic names to domains

  const tax_cats = _.uniq(_.sortBy(Object.values(tax_map)))
  const all_taxa = _.uniq(Object.keys(tax_map)).sort((a, b) =>
    sort_by_category(a, b, (name) => tax_cats.indexOf(tax_map[name]))
  )

  // create count matrix for the outer ring
  // the difference is that this is aggregated
  const annotation_cats = [...new Set(Object.values(ec_map))]
  const all_annotations = _.uniq(Object.keys(ec_map)).sort((a, b) =>
    sort_by_category(a, b, (name) => annotation_cats.indexOf(ec_map[name]))
  )

  const outer_matrix_index = ['gap_1'].concat(
    annotation_cats, // super pathways
    ['gap_2'],
    tax_cats, // domains
    ['gap_3']
  )
  const outer_count_matrix = make_count_matrix(data, outer_matrix_index, tax_map, ec_map)

  // create count matrix for the inner ring
  // sort species by category
  const inner_matrix_index = ['gap_1'].concat(
    all_annotations, // all the ec numbers that are in the map (so excluding 0.0.0.0)
    ['gap_2'],
    all_taxa, // all species
    ['gap_3']
  )

  const inner_count_matrix = make_count_matrix(data, inner_matrix_index)

  // trim inner matrix
  const idx_to_keep = inner_count_matrix.reduce((acc, e, i) => {
    if (d3.sum(e) > 0) acc.push(i)
    return acc
  }, [])
  const trimmed_inner_count_matrix = idx_to_keep.map((e) =>
    idx_to_keep.map((e2) => inner_count_matrix[e][e2])
  )
  const trimmed_inner_matrix_idx = idx_to_keep.map((e) => inner_matrix_index[e])

  const cat_colors = Object.fromEntries([
    ...annotation_cats.map((e, i, arr) => [e, get_color(i, arr.length)]),
    ...tax_cats.map((e, i, arr) => [e, get_color(i, arr.length)])
  ])
  const sub_colors = Object.fromEntries([
    ...all_annotations.map((e, i, arr) => [e, get_sub_color(cat_colors[ec_map[e]], e)]),
    ...all_taxa.map((e, i, arr) => [e, get_sub_color(cat_colors[tax_map[e]], e)])
  ])
  const colors = {
    ...cat_colors,
    ...sub_colors
  }

  return {
    inner_count_matrix: trimmed_inner_count_matrix,
    inner_matrix_index: trimmed_inner_matrix_idx,
    outer_count_matrix,
    outer_matrix_index,
    colors,
    tax_map,
    ann_map: ec_map
  }
}

const make_1d_count_matrix = (data: Array<object>, tax_map: object) => {
  // a simplified count matrix that just tallies the total RPKM mapped to each taxonomic category
  const tax_cats = _.uniq(_.sortBy(Object.values(tax_map)))
  const all_taxa = _.uniq(Object.keys(tax_map))
  const counts = Object.fromEntries(tax_cats.map((e) => [e, []]))
  data.forEach((e) => {
    all_taxa.forEach((t) => {
      const cat = tax_map[t]
      const val = Number(e[t])
      if (cat && val > 0) counts[cat].push(val)
    })
  })
  return {
    counts_idx: tax_cats,
    counts: tax_cats.map((e) => d3.mean(counts[e]))
  }
}

// main data parsing function for the front end
// we should run this once to save time between tab switches
const parse_data = (
  data: Array<object>,
  ec_data: Array<object>,
  tax_level: string,
  ann_level: string
) => {
  // first we need to get the taxonomic grouping, then do the actual parsing
  useAppStore.setState({ isLoading: true })
  const tax_terms = Object.keys(data[0]).filter((e) => !key_cols.includes(e))
  const ec_mapping = Object.fromEntries(
    ec_data.map((e) => [e['ec'], ann_level === 'pathway' ? e['pathway_name'] : e['superpathway']])
  )
  window.electron.ipcRenderer.once('got-tax-cats', (_event, tax_map) => {
    const parsed_data = parse_data_callback(data, ec_mapping, tax_map)
    const counts_data = make_1d_count_matrix(data, tax_map)
    useAppStore.setState({
      parsed_data: parsed_data,
      parsed_counts_data: counts_data,
      isLoading: false
    })
  })
  window.electron.ipcRenderer.send('get-tax-cats', tax_terms, tax_level)
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
      name: label, // generally should be species
      value: data[id],
      percentage: data[id] / total
    }
  } else {
    const tax_tree_subsets = group_tax_tree_at_level(tax_tree, levels[0])
    const children = tax_tree_subsets.map(({ subset_name, subset }) => {
      return parse_tax_tree_recursive(data, subset, levels.slice(1), subset_name, total)
    })
    return {
      name,
      children,
      percentage: d3.sum(children.map((e) => e.percentage))
    }
  }
}

const parse_tax_tree = (data, tax_tree, levels) => {
  // this makes use the 1D matrix function but do not aggregate to taxonomic categories
  // by using self_map instead of a real tax_map so each entry is its own category
  const self_map = Object.fromEntries(tax_tree.map((e) => [e.id, e.id]))
  const { counts_idx, counts } = make_1d_count_matrix(data, self_map)
  const parsed_data = Object.fromEntries(counts_idx.map((e, i) => [e, counts[i]]))
  const total = d3.sum(Object.values(parsed_data))
  return parse_tax_tree_recursive(parsed_data, tax_tree, levels, 'root', total)
}

// this is the function to call when data is first uploaded
// it is broader than parse_data
const get_krona_data = (data: Array<object>) => {
  const tax_terms = Object.keys(data[0]).filter((e) => !key_cols.includes(e))
  const levels = ['phylum', 'genus', 'species']
  window.electron.ipcRenderer.once('got-tax-tree', (_event, tax_tree) => {
    const krona_data = parse_tax_tree(data, tax_tree, levels)
    useAppStore.setState({ krona_data })
  })
  window.electron.ipcRenderer.send('get-tax-tree', tax_terms, levels)
}
export { parse_data, get_krona_data }
