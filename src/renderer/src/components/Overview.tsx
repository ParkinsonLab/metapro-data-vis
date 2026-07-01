// Overview pane: small pies summarizing the loaded dataset's expression and
// metabolism breakdown. Clicking a pie navigates to the matching detail view.

import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import { request } from '../api'
import * as d3 from 'd3'
import { useEffect, useRef } from 'react'

// Inline copy of the project's HSL color generator. Lives in src/main/utils.ts
// today; renderer code shouldn't reach into the main process tree, so we copy
// the four-line implementation here. Move to src/shared/ when one exists.
const get_color = (i: number, n: number): string =>
  `hsl(${Math.trunc((360 / (n + 1)) * i)} 75 50)`

const label_map: Record<string, string> = {
  counts: 'Expression',
  ann: 'Metabolism'
}
const state_map: Record<string, 'krona' | 'chord'> = {
  counts: 'krona',
  ann: 'chord'
}

const OverviewSection = ({
  id,
  index,
  counts
}: {
  id: 'counts' | 'ann'
  index: string[]
  counts: number[]
}): React.JSX.Element => {
  const base_radius = 50
  const rad_step = 10
  const width = 125
  const height = 125

  const ref = useRef<SVGSVGElement>(null)

  const handleClick = (): void => {
    useAppStore.setState({ mainState: state_map[id] })
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
      .attr('height', height)
      .attr('viewBox', `${-width / 2} ${-height / 2} ${width} ${height}`)
      .attr('style', 'max-width: 100%; height: auto; font: 10px sans-serif black; z-index: 10;')

    const data = index.map((e, i) => ({ id: e, value: counts[i] }))
    const pie = d3
      .pie<{ id: string; value: number }>()
      .value((d) => d.value)
      .sort(null) // preserve backend index order for arc position (see overview design spec §4.2)
    const colors = d3.scaleOrdinal(
      index,
      index.map((_, i, arr) => get_color(i, arr.length))
    )

    const nodes = svg.append('g').selectAll('g').data(pie(data)).join('g')

    nodes
      .append('path')
      .attr('fill', (d) => colors(d.data.id))
      .attr('d', arc as any)
      .attr('stroke', 'black')
      .append('title')
      .text((d) => d.data.id)
  }, [index, counts])

  return (
    <div className="overview-parent" id={`overview-${id}-parent`} onClick={handleClick}>
      <div id={`overview-${id}`}>
        <svg width={width} height={height} ref={ref} />
      </div>
      <span className="overview-label bold">{label_map[id]}</span>
    </div>
  )
}

const Overview = (): React.JSX.Element => {
  const overview_data = useAppStore((state) => state.overview_data)
  const selected_file_list = useAppStore((state) => state.selected_file_list)
  const { counts_data, ann_data } = overview_data ?? {}

  // Fetch on mount whenever files are selected. Effect re-runs when the file
  // list reference changes, so picking new files in Upload and coming back
  // here triggers a fresh fetch.
  useEffect(() => {
    if (selected_file_list.length === 0) return
    request('overview', { names: selected_file_list })
  }, [selected_file_list])

  if (selected_file_list.length === 0) {
    return (
      <div id="overview-container">
        <p>Load and select files in the Upload tab to see the overview.</p>
      </div>
    )
  }

  const ready = !_.isEmpty(counts_data) && !_.isEmpty(ann_data)

  return (
    <div id="overview-container">
      {ready && (
        <>
          <OverviewSection id="counts" index={counts_data.index} counts={counts_data.counts} />
          <OverviewSection id="ann" index={ann_data.index} counts={ann_data.counts} />
        </>
      )}
    </div>
  )
}

export default Overview
