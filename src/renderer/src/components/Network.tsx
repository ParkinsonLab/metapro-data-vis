import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import * as d3 from 'd3'
import { useState, useEffect, useRef } from 'react'
import { request } from '../api'

// ---------------------------------------------------------------------------
// Network pane
//
// Two views, switched on `selected_pathway`:
//   - PathwayList: clickable grid of pathway names within the currently
//     selected superpathway. Picking one fires a `network` request.
//   - PathwayDetail: full d3 network for the selected pathway, fed entirely
//     by `network_data` from the store (no client-side aggregation).
//
// Pre-PR5 this component leaned on a `parsed_data` blob and a deleted
// `parse.ts` for client-side tax aggregation, neither of which exist anymore.
// ---------------------------------------------------------------------------

const draw_elbow_line = (x1: number, y1: number, x2: number, y2: number): string => {
  const dx = x2 - x1
  const dy = y2 - y1
  const min_arc = 1
  const arc_f = 0.8

  if (Math.abs(dx) <= min_arc) return `M ${x1},${y1} v ${dy}`
  if (Math.abs(dy) <= min_arc) return `M ${x1},${y1} h ${dx}`

  const m1 = Math.abs(dy) >= Math.abs(dx) ? 'v' : 'h'
  const r_basis = m1 === 'v' ? dx : dy
  const r = Math.abs(r_basis * (1 - arc_f))
  const rdx = r * Math.sign(dx)
  const rdy = r * Math.sign(dy)
  const v1 = m1 === 'v' ? dy - rdy : dx - rdx
  const m2 = m1 === 'v' ? 'h' : 'v'
  const v2 = m2 === 'v' ? dy - rdy : dx - rdx

  let sweep
  if (m1 === 'v') {
    sweep = dy * dx >= 0 ? 0 : 1
  } else {
    sweep = dy * dx >= 0 ? 1 : 0
  }
  return `M ${x1},${y1} ${m1} ${v1} a ${r} ${r} 0 0 ${sweep} ${rdx},${rdy} ${m2} ${v2}`
}

const get_symbol = (type: string, size: number): string => {
  let s_type
  if (type === 'circle') s_type = d3.symbolCircle
  else if (type === 'rectangle') s_type = d3.symbolSquare
  else s_type = d3.symbolDiamond
  return d3.symbol(s_type, size)() ?? ''
}

interface PathwayNode {
  id: string
  label: string
  type: string
  x: number
  y: number
  values: { id: string; value: number }[]
}

interface PathwayEdge {
  source: PathwayNode
  target: PathwayNode
}

interface NetworkData {
  nodes: PathwayNode[]
  edges: PathwayEdge[]
  colors: Record<string, string>
}

const PathwayDetail = ({
  base_width,
  base_height,
  pathway,
  network_data
}: {
  base_width: number
  base_height: number
  pathway: string
  network_data: NetworkData
}): React.JSX.Element => {
  const max_label_length = 11
  const ref = useRef<SVGSVGElement>(null)
  const selected_annotations = useAppStore((state) => state.selected_annotations)

  const [zoom, set_zoom] = useState(1)
  const [view_offset, set_view_offset] = useState({
    x: -base_width / 2,
    y: -base_height / 2
  })
  const [dragging, set_dragging] = useState(false)
  const drag_start = useRef({ x: 0, y: 0 })

  const handleWheel = (event: React.WheelEvent<SVGSVGElement>): void => {
    const max_factor = 3
    const min_factor = 1
    set_zoom((curr) => {
      const next = event.deltaY <= 0 ? curr - 0.1 : curr + 0.1
      return next >= min_factor ? Math.min(next, max_factor) : min_factor
    })
  }

  const handleMouseDown = (event: React.MouseEvent<SVGSVGElement>): void => {
    if (ref.current && event.button === 0 && event.target === ref.current) {
      set_dragging(true)
      drag_start.current = { x: event.clientX, y: event.clientY }
    }
  }

  const handleMouseUp = (): void => {
    set_dragging(false)
  }

  const handleMouseMove = (event: React.MouseEvent<SVGSVGElement>): void => {
    if (!dragging) return
    const { x, y } = drag_start.current
    const dx = event.clientX - x
    const dy = event.clientY - y
    drag_start.current = { x: event.clientX, y: event.clientY }
    set_view_offset((curr) => ({ x: curr.x - dx, y: curr.y - dy }))
  }

  const handle_node_click = (_event: unknown, d: PathwayNode): void => {
    if (selected_annotations.includes(d.label)) {
      useAppStore.setState({ selected_annotations: _.without(selected_annotations, d.label) })
    } else {
      useAppStore.setState({ selected_annotations: [...selected_annotations, d.label] })
    }
  }

  const handle_back_click = (): void => {
    useAppStore.setState({ selected_pathway: '', network_data: {} })
  }

  useEffect(() => {
    const width = base_width * zoom
    const height = base_height * zoom
    const node_size = Math.min(height, width) / 10

    const { nodes, edges, colors } = network_data
    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()
    svg
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', [view_offset.x * zoom, view_offset.y * zoom, base_width, base_height])
      .attr('style', 'max-width: 100%; height: auto')

    svg
      .append('g')
      .selectAll('path')
      .data(edges.filter((e) => e.source && e.target))
      .join('path')
      .attr('d', (d) => draw_elbow_line(d.source.x, d.source.y, d.target.x, d.target.y))
      .attr('fill', 'none')
      .attr('stroke', 'grey')
      .attr('stroke-width', 0.5)

    svg
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join((enter) => {
        const g = enter.append('g')
        g.each(function (this: SVGGElement, d: PathwayNode) {
          const base_radius = Math.sqrt(node_size) / 2
          const arc = d3
            .arc<d3.PieArcDatum<{ id: string; value: number }>>()
            .innerRadius(base_radius / 0.5)
            .outerRadius(base_radius)
          const pie = d3.pie<{ id: string; value: number }>().value((d2) => d2.value)
          const pie_g = d3.select(this)
          pie_g.attr('transform', `translate(${d.x}, ${d.y})`)

          pie_g
            .insert('path', null)
            .attr('d', get_symbol(d.type, node_size))
            .attr('fill', selected_annotations.includes(d.label) ? 'orange' : 'black')
            .on('click', (event) => handle_node_click(event, d))
            .append('title')
            .text(d.label)

          pie_g
            .selectAll('.pie-wedge')
            .data(pie(d.values))
            .join('path')
            .attr('d', arc)
            .attr('fill', (d2) => colors[d2.data.id] ?? 'lightgray')

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
  }, [network_data, selected_annotations, zoom, view_offset, base_width, base_height])

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

const PathwayCard = ({
  pathway,
  width,
  height
}: {
  pathway: string
  width: number
  height: number
}): React.JSX.Element => {
  const selected_file_list = useAppStore((state) => state.selected_file_list)
  const selected_taxon = useAppStore((state) => state.selected_taxon) as {
    level?: string
    name?: string
  }
  const tax_rank = useAppStore((state) => state.tax_rank)

  const handle_click = (): void => {
    useAppStore.setState({ selected_pathway: pathway })
    request('network', {
      names: selected_file_list,
      tax_level: tax_rank,
      selected_taxon: selected_taxon ?? {},
      pathway_name: pathway,
      width: 900,
      height: 550
    })
  }

  return (
    <div
      onClick={handle_click}
      className="pathway-preview-item"
      style={{
        width,
        height,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: 4,
        border: '1px solid #ccc',
        cursor: 'pointer',
        boxSizing: 'border-box',
        fontSize: 12,
        overflow: 'hidden'
      }}
      title={pathway}
    >
      <span>{pathway}</span>
    </div>
  )
}

const PathwayList = ({
  height,
  width,
  superpathway,
  pathways
}: {
  height: number
  width: number
  superpathway: string
  pathways: string[]
}): React.JSX.Element => {
  if (pathways.length === 0) {
    return (
      <div id="pathway-preview-outer-container">
        <div className="bold" id="network-title">
          {`Superpathway: ${superpathway}`}
        </div>
        <div style={{ padding: 16 }}>No pathways found in this superpathway.</div>
      </div>
    )
  }
  const grid_size = Math.ceil(Math.sqrt(pathways.length))
  const c_width = width / grid_size
  const c_height = height / grid_size
  return (
    <div id="pathway-preview-outer-container">
      <div className="bold" id="network-title">
        {`Superpathway: ${superpathway}`}
      </div>
      <div
        id="pathway-preview-container"
        style={{ display: 'flex', flexWrap: 'wrap', width, height }}
      >
        {pathways.map((p) => (
          <PathwayCard key={p} pathway={p} width={c_width} height={c_height} />
        ))}
      </div>
    </div>
  )
}

const Network = (): React.JSX.Element => {
  const width = 900
  const height = 550

  const selected_pathway = useAppStore((state) => state.selected_pathway)
  const selected_ann_cat = useAppStore((state) => state.selected_ann_cat) as
    | string
    | { level?: string; name?: string }
  const network_data = useAppStore((state) => state.network_data) as NetworkData | object
  const pathway_list = useAppStore((state) => state.pathway_list)

  // selected_ann_cat is set in two slightly different shapes depending on
  // history: a bare superpathway name (string) when picked from chord, or an
  // empty object on reset. Normalize.
  const superpathway_name =
    typeof selected_ann_cat === 'string' ? selected_ann_cat : (selected_ann_cat?.name ?? '')

  // Fetch the pathway list whenever the active superpathway changes.
  useEffect(() => {
    if (!superpathway_name) return
    request('pathway_list', { superpathway: superpathway_name })
  }, [superpathway_name])

  if (!superpathway_name) {
    return (
      <div id="network-container" style={{ padding: 16 }}>
        Select a superpathway in the Chord view to see its pathways here.
      </div>
    )
  }

  const detail_ready =
    selected_pathway &&
    network_data &&
    !_.isEmpty(network_data) &&
    Array.isArray((network_data as NetworkData).nodes)

  return (
    <div>
      {detail_ready ? (
        <PathwayDetail
          base_width={width}
          base_height={height}
          pathway={selected_pathway}
          network_data={network_data as NetworkData}
        />
      ) : (
        <PathwayList
          width={width}
          height={height}
          superpathway={superpathway_name}
          pathways={pathway_list}
        />
      )}
    </div>
  )
}

export default Network
