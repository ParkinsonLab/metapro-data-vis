import Plot from 'react-plotly.js'
import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import { useState, useEffect, useRef } from 'react'

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
  // do not mount without first checking if parsed_data is available

  const parsed_data = useAppStore((state) => state.parsed_data)
  const selected_annotations = useAppStore((state) => state.selected_annotations)
  const [plot_data, set_plot_data] = useState<PlotTrace[]>([])
  const [plot_layout, set_plot_layout] = useState({})

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
    const {
      inner_count_matrix,
      inner_matrix_index,
      outer_count_matrix,
      outer_matrix_index,
      colors,
      tax_map,
      ann_map
    } = parsed_data

    const selected_idx = selected_annotations.map((e) => inner_matrix_index.indexOf(e))
    const tax_idx_start = inner_matrix_index.indexOf('gap_2') + 1
    const tax_idx_end = inner_matrix_index.indexOf('gap_3')
    const tax_idc = [...Array(tax_idx_end - tax_idx_start).keys()].map((e) => e + tax_idx_start)
    const subset_data = selected_idx.map((i) => tax_idc.map((j) => inner_count_matrix[i][j]))
    const tax_vals = Array.from(tax_idc.keys())
    const t_data = subset_data.map((e, i) => ({
      ...trace_props,
      x: Array(e.length).fill(i),
      y: tax_vals,
      z: e,
      name: selected_annotations[i],
      line: {
        color: colors[selected_annotations[i]],
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
        [0, colors[e]],
        [1, colors[e]]
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
        y: 0.95, // Move title closer to plot (default is 1.0)
        yanchor: 'top'
      },
      scene: {
        xaxis: {
          title: { text: 'ECs', font: { color: 'black' } },
          gridcolor: 'black',
          range: [-1, subset_data.length],
          tickvals: [...subset_data.keys()],
          ticktext: selected_annotations,
          ticklabelposition: 'outside bottom',
          color: 'black',
          tickfont: { color: 'black' }
        },
        yaxis: {
          title: { text: 'Toxonomy', font: { color: 'black' } },
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
          range: [0, Math.max(...subset_data.flat()) + 5],
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
  }, [parsed_data])

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
