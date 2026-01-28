import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import * as d3 from 'd3'
import { useState, useEffect, useRef } from 'react'

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

const draw_elbow_line = (x1, y1, x2, y2) => {
  const dx = x2 - x1
  const dy = y2 - y1
  const min_arc = 1
  const arc_f = 0.8 // when to start turning

  // don't draw arc if it's almost horizontal or vertical
  if (Math.abs(dx) <= min_arc) return `M ${x1},${y1} v ${dy}`
  if (Math.abs(dy) <= min_arc) return `M ${x1},${y1} h ${dx}`

  // calculations if we're drawing an arc
  const m1 = Math.abs(dy) >= Math.abs(dx) ? 'v' : 'h' // mode of the first line

  // we need to calculate for the arc before we know how much v1 can be
  const r_basis = m1 === 'v' ? dx : dy
  const r = Math.abs(r_basis * (1 - arc_f))
  const rdx = r * Math.sign(dx)
  const rdy = r * Math.sign(dy)

  const v1 = m1 === 'v' ? dy - rdy : dx - rdx // value of the first line

  const m2 = m1 === 'v' ? 'h' : 'v' // second segment's mode
  const v2 = m2 === 'v' ? dy - rdy : dx - rdx // second segment length

  let sweep
  if (m1 === 'v') {
    sweep = dy * dx >= 0 ? 0 : 1
  } else {
    sweep = dy * dx >= 0 ? 1 : 0
  }
  const d = `M ${x1},${y1} ${m1} ${v1} a ${r} ${r} 0 0 ${sweep} ${rdx},${rdy} ${m2} ${v2}`
  return d
}

const get_symbol = (type, size) => {
  let s_type
  if (type === 'circle') {
    s_type = d3.symbolCircle
  } else if (type === 'rectangle') {
    s_type = d3.symbolSquare
  } else {
    s_type = d3.symbolDiamond
  }
  return d3.symbol(s_type, size)()
}

const Pathway = ({ base_width, base_height, pathway, ann_map }): React.JSX.Element => {
  // Do not mount this component without checking that data exists
  // Check at parent level
  // Since this replaces the preview panel, network data should not be able to
  // change while this is mounted

  // set data load callback
  const max_label_length = 11
  const ref = useRef<SVGSVGElement>(null)
  const selected_annotations = useAppStore((state) => state.selected_annotations)

  // reformat data
  const parsed_data = useAppStore((state) => state.parsed_data)
  const network_data = useAppStore((state) => state.network_data)

  // for pan and zoom
  const [zoom, set_zoom] = useState(1)
  const [view_offset, set_view_offset] = useState({
    x: -base_width / 2,
    y: -base_height / 2
  })
  const [dragging, set_dragging] = useState(false)
  const drag_start = useRef({ x: 0, y: 0 })

  const handleWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    const max_factor = 3
    const min_factor = 1

    set_zoom((curr) => {
      const n_f = event.deltaY <= 0 ? curr - 0.1 : curr + 0.1
      return n_f >= min_factor ? Math.min(n_f, max_factor) : min_factor
    })
  }

  const handleMouseDown = (event: React.MouseEvent<SVGSVGElement>) => {
    // We want to allow dragging starting from background only (svg element, not child)
    if (
      ref.current &&
      event.button === 0 &&
      event.target === ref.current // only if the click is on background
    ) {
      console.log('m_down')
      set_dragging(true)
      drag_start.current = {
        x: event.clientX,
        y: event.clientY
      }
    }
  }

  const handleMouseUp = (_event: React.MouseEvent<SVGSVGElement>) => {
    if (ref.current) {
      console.log('m_up')
      set_dragging(false)
    }
  }

  const handleMouseMove = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!dragging) return

    const { x, y } = drag_start.current
    const dx = event.clientX - x
    const dy = event.clientY - y
    drag_start.current = { x: event.clientX, y: event.clientY }
    console.log(event.clientX, event.clientY)
    set_view_offset((curr) => ({
      x: curr.x - dx,
      y: curr.y - dy
    }))
  }

  const handle_node_click = (_event, d) => {
    console.log(d)
    if (selected_annotations.includes(d.label)) {
      useAppStore.setState({ selected_annotations: _.without(selected_annotations, d.label) })
    } else {
      useAppStore.setState({ selected_annotations: [...selected_annotations, d.label] })
    }
  }

  const handle_back_click = (_event) => {
    console.log('click_back')
    useAppStore.setState({ selected_pathway: '' })
  }

  useEffect(() => {
    console.log('pathway_redraw')
    const width = base_width * zoom
    const height = base_height * zoom

    const node_size = Math.min(height, width) / 10

    const plot_data = get_formatted_network_data(
      parsed_data,
      network_data,
      pathway,
      ann_map,
      height,
      width
    )

    const { nodes, edges, colors } = plot_data
    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()
    svg
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', [view_offset.x * zoom, view_offset.y * zoom, base_width, base_height])
      .attr('style', 'max-width: 100%; height: auto')

    // links
    const link_selection = svg
      .append('g')
      .selectAll('line')
      .data(edges)
      .join('path')
      .attr('d', (d) => draw_elbow_line(d.source.x, d.source.y, d.target.x, d.target.y))
      .attr('fill', 'none')
      .attr('stroke', 'grey')
      .attr('stroke-width', 0.5)

    const node_selection = svg
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join((enter) => {
        const g = enter.append('g')
        g.each(function (d) {
          // For each toy_data row, construct the arc pie pieces within this 'g'
          const base_radius = Math.sqrt(node_size) / 2
          const arc = d3
            .arc()
            .innerRadius(base_radius / 0.5)
            .outerRadius(base_radius)
          // d is an array; generate pie data manually
          const pie = d3.pie().value((d2) => d2.value)
          const pie_g = d3.select(this)
          pie_g.attr('transform', `translate(${d.x}, ${d.y})`)

          // First, append the symbol path (so it goes below the pie wedges)
          const symbolPath = pie_g
            .insert('path', null)
            .attr('d', get_symbol(d.type, node_size))
            .attr('fill', selected_annotations.includes(d.label) ? 'orange' : 'black')
            .on('click', (event) => handle_node_click(event, d))
            .append('title')
            .text(d.label)

          // Then, append the pie wedge paths so they're rendered above the symbol
          pie_g
            .selectAll('.pie-wedge')
            .data(pie(d.values))
            .join('path')
            .attr('d', arc)
            .attr('fill', (d2) => colors[d2.data.id])

          // Append label text directly beneath the symbol
          pie_g
            .append('text')
            .attr('x', 0)
            .attr('y', base_radius + 6)
            .attr('text-anchor', 'middle')
            .attr('alignment-baseline', 'hanging')
            .attr('font-size', base_radius * 2 - 2)
            .attr('fill', 'black')
            .text(
              d.label.substring(0, 1) === 'C'
                ? ''
                : d.label.length > max_label_length
                  ? d.label.substring(0, max_label_length) + '...'
                  : d.label
            )
        })
        return g
      })
  }, [selected_annotations, zoom, view_offset])

  return (
    <div id="pathway-container">
      <div id="top-row">
        <span id="pathway-back-button" className="bold" onClick={handle_back_click}>
          {'< Back'}
        </span>
        <span id="pathway-title">{pathway}</span>
      </div>
      <svg
        width={base_width}
        height={base_height}
        id="network"
        ref={ref}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{ cursor: dragging ? 'grabbing' : 'default' }}
      />
    </div>
  )
}

const PathwayPreview = ({
  height,
  width,
  pathway,
  ann_map
}: {
  height: number
  width: number
  pathway: string
  ann_map: Record<string, string>
}): React.JSX.Element => {
  const ref = useRef<SVGSVGElement>(null)
  const base_radius = Math.min(height, width) * 0.3
  const rad_step = Math.ceil(base_radius * 0.2)
  const text_height = 25

  const parsed_data = useAppStore((state) => state.parsed_data)
  const ec_data = useAppStore((state) => state.ec)
  const { inner_count_matrix, inner_matrix_index, tax_map: tax_map, colors } = parsed_data
  const { data, ann_idx, tax_idx } = subset_data(
    inner_count_matrix,
    inner_matrix_index,
    (e) => ann_map[e] === pathway
  )
  const { data: condensed_data, tax_cats } = condense_to_tax_group(data, tax_idx, tax_map)
  const pie_data = tax_cats.map((e, i) => ({
    id: e,
    value: d3.sum(condensed_data.map((e2) => e2[i]))
  }))

  const handle_click = (event) => {
    console.log('handle click on preview')
    const pathway_id = _.find(ec_data, (e) => e.pathway_name === pathway)['pathway_id']
    useAppStore.setState({ isLoading: true })
    window.electron.ipcRenderer.once('return-node-info', (_, data) => {
      console.log('network_data', data)
      useAppStore.setState({ network_data: data, selected_pathway: pathway, isLoading: false })
    })
    window.electron.ipcRenderer.send('request-node-info', pathway_id)
  }

  useEffect(() => {
    const arc = d3
      .arc()
      .innerRadius(base_radius)
      .outerRadius(base_radius + rad_step)

    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()
    svg
      .attr('width', width)
      .attr('height', height - text_height)
      .attr('viewBox', [-width / 2, -height / 2, width, height])
      .attr('style', 'font: 10px sans-serif black;')

    const pie = d3.pie().value((d) => d.value)
    // node here isn't network nodes, it's the nodes of the arc for the pie
    const nodes = svg.append('g').selectAll().data(pie(pie_data)).join('g')

    nodes
      .append('path') // draw arc
      .attr('fill', (d) => colors[d.data.id])
      .attr('d', arc)
      .attr('stroke', 'black')
      .append('title')
      .text((d) => d.data.id)
  }, [])

  return (
    <div
      onClick={handle_click}
      className="pathway-preview-item"
      style={{ height: height, width: width }}
    >
      <svg ref={ref} />
      <span className="pathway-preview-item-name">{pathway}</span>
    </div>
  )
}

const PathwayPreviewContainer = ({ height, width, superpathway, ann_map }) => {
  // prevent mounting of this element if parrsed_data is null at the parent level
  // here we assume that it has been loaded

  const pathways = _.uniq(Object.values(ann_map))
  const grid_size = Math.ceil(Math.sqrt(pathways.length))
  const c_width = width / grid_size
  const c_height = height / grid_size
  const elements = pathways.map((e) => (
    <PathwayPreview height={c_height} width={c_width} pathway={e} ann_map={ann_map} key={e} />
  ))

  return (
    <div id="pathway-preview-outer-container">
      <div className="bold" id="network-title">
        {'Superpathway: ' + superpathway}
      </div>
      <div id="pathway-preview-container">{elements}</div>
    </div>
  )
}

const Network = (): React.JSX.Element => {
  // parsed_data emptiness checks are done at the parent level

  const width = 900
  const height = 550

  const selected_pathway = useAppStore((state) => state.selected_pathway)
  const network_data = useAppStore((state) => state.network_data)
  const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
  const ec_data = useAppStore((state) => state.ec)

  // Here we map to pathway level regardless of what was selected in the above
  const ann_map = Object.fromEntries(
    ec_data
      .filter((e) => e['superpathway'] === selected_ann_cat)
      .map((e) => [e['ec'], e['pathway_name']])
  )

  return (
    <div>
      {selected_pathway && !_.isEmpty(network_data) ? (
        <Pathway
          base_width={width}
          base_height={height}
          pathway={selected_pathway}
          ann_map={ann_map}
        />
      ) : (
        <PathwayPreviewContainer
          width={width}
          height={height}
          superpathway={selected_ann_cat}
          ann_map={ann_map}
        />
      )}
    </div>
  )
}

export default Network
