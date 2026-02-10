
// this needs the inner matrix and index
const subset_data = (data_matrix, data_matrix_index, annotation_checker) => {
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
  
  const condense_to_tax_group = (data_matrix, tax_index, tax_map) => {
    // condenses the 2nd dimension (taxonomy) to the group level, according to tax_map
  
    const tax_cats = _.uniq(Object.values(tax_map))
    return {
      data: data_matrix.map((e) =>
        e.reduce(
          (acc, e2, i) => {
            acc[tax_cats.indexOf(tax_map[tax_index[i]])] += e2
            return acc
          },
          tax_cats.map((_) => 0)
        )
      ),
      tax_cats
    }
  }
  
  const get_formatted_network_data = (parsed_data, network_data, pathway, ann_map, height, width) => {
    // add counts information to network_data
    // use datastore data
  
    const { inner_count_matrix, inner_matrix_index, colors, tax_map } = parsed_data
    const { data, ann_idx, tax_idx } = subset_data(
      inner_count_matrix,
      inner_matrix_index,
      (e) => ann_map[e] === pathway
    )
  
    const { data: condensed_data, tax_cats } = condense_to_tax_group(data, tax_idx, tax_map)
  
    const new_nodes = network_data.nodes.map((e) => {
      return {
        ...e,
        x: (e.y / 1100) * width - width / 2 + 100,
        y: (e.x / 1000) * height - height / 2,
        values: ann_idx.includes(e.label)
          ? condensed_data[ann_idx.indexOf(e.label)].map((e, i) => ({
              id: tax_cats[i],
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