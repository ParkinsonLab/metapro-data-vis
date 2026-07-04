import Plot from 'react-plotly.js'
import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import { useState, useEffect } from 'react'
import { request } from '../api'
import { toApiFilter } from '../chordFilters'

type PlotTrace = {
  z: number[]
  x: number[]
  y: number[]
  line: {
    color: string
    width: number
  }
  mode: string
  type: string
  name: string
}

function Graph(): React.JSX.Element {
  const graph_data = useAppStore((state) => state.graph_data)
  const selected_annotations = useAppStore((state) => state.selected_annotations)
  const selected_file_list = useAppStore((state) => state.selected_file_list)
  const tax_rank = useAppStore((state) => state.tax_rank)
  const ann_rank = useAppStore((state) => state.ann_rank)
  const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
  const selected_taxon = useAppStore((state) => state.selected_taxon)
  const [plot_data, set_plot_data] = useState<PlotTrace[]>([])
  const [plot_layout, set_plot_layout] = useState({})
  const [plot_message, set_plot_message] = useState<string | null>(null)

  const trace_props = {
    mode: 'lines',
    type: 'scatter3d'
  }
  const bg_props = {
    type: 'surface',
    showlegend: false,
    showscale: false,
    z: [
      [0, 0],
      [0, 0]
    ]
  }

  useEffect(() => {
    request('graph', {
      names: selected_file_list,
      tax_level: tax_rank,
      ann_level: ann_rank,
      selected_ann_cat: toApiFilter(selected_ann_cat),
      selected_taxon: toApiFilter(selected_taxon)
    })
  }, [selected_file_list, tax_rank, ann_rank, selected_ann_cat, selected_taxon])

  useEffect(() => {
    if (!graph_data || _.isEmpty(graph_data)) return

    const {
      inner_count_matrix,
      inner_matrix_index,
      outer_matrix_index,
      colors,
      tax_map
    } = graph_data

    const selected = selected_annotations
      .map((label) => ({ label, idx: inner_matrix_index.indexOf(label) }))
      .filter((e) => e.idx >= 0)

    if (selected.length === 0) {
      set_plot_data([])
      set_plot_layout({})
      set_plot_message(
        'Selected ECs are not in the current graph data. Try clearing chord filters or re-selecting ECs in Network.'
      )
      return
    }

    const tax_gap2 = inner_matrix_index.indexOf('gap_2')
    const tax_gap3 = inner_matrix_index.indexOf('gap_3')
    if (tax_gap2 < 0 || tax_gap3 < 0 || tax_gap3 <= tax_gap2 + 1) {
      set_plot_data([])
      set_plot_layout({})
      set_plot_message('Graph data is missing taxonomy columns.')
      return
    }

    set_plot_message(null)

    const tax_idx_start = tax_gap2 + 1
    const tax_idx_end = tax_gap3
    const tax_idc = [...Array(tax_idx_end - tax_idx_start).keys()].map((e) => e + tax_idx_start)
    const subset_data = selected.map(({ idx }) =>
      tax_idc.map((j) => inner_count_matrix[idx][j])
    )
    const tax_vals = Array.from(tax_idc.keys())
    const t_data = subset_data.map((e, i) => ({
      ...trace_props,
      x: Array(e.length).fill(i),
      y: tax_vals,
      z: e,
      name: selected[i].label,
      line: {
        color: colors?.[selected[i].label] ?? 'gray',
        width: 2
      }
    }))
    const tax_cats = outer_matrix_index.slice(
      outer_matrix_index.indexOf('gap_2') + 1,
      outer_matrix_index.indexOf('gap_3')
    )
    const tax_cat_counts = tax_idc
      .map((e) => tax_map[inner_matrix_index[e]])
      .reduce(
        (acc, e) => {
          acc[e] += 1
          return acc
        },
        Object.fromEntries(tax_cats.map((e) => [e, 0]))
      )
    const tax_cat_csum = tax_cats.reduce((acc, e) => {
      const prev = acc[acc.length - 1]
      acc.push(tax_cat_counts[e] + prev)
      return acc
    }, Array(1).fill(0))
    const t_bg = tax_cats.map((e, i) => ({
      ...bg_props,
      x: [subset_data.length - 0.5, subset_data.length],
      y: [Math.max(tax_cat_csum[i] - 1, 0), tax_cat_csum[i + 1] - 1],
      colorscale: [
        [0, colors?.[e] ?? 'lightgray'],
        [1, colors?.[e] ?? 'lightgray']
      ],
      opacityscale: [
        [0, 0.2],
        [1, 0.2]
      ],
      name: e
    }))
    const t_data_2 = _.concat(t_data, t_bg)
    set_plot_data(t_data_2)

    const t_layout = {
      title: {
        text: 'RPKM for selected ECs',
        font: { color: 'black' },
        y: 0.95,
        yanchor: 'top'
      },
      scene: {
        xaxis: {
          title: { text: 'ECs', font: { color: 'black' } },
          gridcolor: 'black',
          range: [-1, subset_data.length],
          tickvals: [...subset_data.keys()],
          ticktext: selected.map((e) => e.label),
          ticklabelposition: 'outside bottom',
          color: 'black',
          tickfont: { color: 'black' }
        },
        yaxis: {
          title: { text: 'Taxonomy', font: { color: 'black' } },
          tickmode: 'array',
          tickvals: tax_cats
            .map((e, i) => tax_cat_csum[i] + tax_cat_counts[e] / 2 - 1)
            .filter((_, i) => tax_cat_counts[tax_cats[i]] > 0),
          ticktext: tax_cats
            .filter((e) => tax_cat_counts[e] > 0)
            .map((k) => k.substring(0, 7) + '...'),
          color: 'black',
          tickfont: { color: 'black' }
        },
        zaxis: {
          title: { text: 'RPKM', font: { color: 'black' } },
          range: [0, Math.max(0, ...subset_data.flat()) + 5],
          color: 'black',
          tickfont: { color: 'black' }
        }
      },
      paper_bgcolor: 'rgb(245, 245, 245)',
      plot_bgcolor: 'rgb(245, 245, 245)',
      autosize: false,
      margin: { l: 0, r: 10, b: 10, t: 10, pad: 0 },
      width: 900,
      height: 600,
      legend: {
        x: 1.0,
        y: 0.5,
        xanchor: 'right',
        yanchor: 'bottom',
        font: { color: 'black' }
      }
    }
    set_plot_layout(t_layout)
  }, [graph_data, selected_annotations])

  if (selected_annotations.length === 0) {
    return (
      <div id="graph-container">
        <p>Select ECs in the Network view to plot RPKM.</p>
      </div>
    )
  }

  if (plot_message) {
    return (
      <div id="graph-container">
        <p>{plot_message}</p>
      </div>
    )
  }

  return (
    <div id="graph-container">
      {!(_.isEmpty(plot_data) || _.isEmpty(plot_layout)) ? (
        <Plot data={plot_data} layout={plot_layout} />
      ) : (
        <div />
      )}
    </div>
  )
}

export default Graph
