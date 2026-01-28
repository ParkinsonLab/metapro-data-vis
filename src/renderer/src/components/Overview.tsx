//Overview graphic with bacterial cell

import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import * as d3 from 'd3'
import { useState, useEffect, useRef } from 'react'
import { get_color } from './util'

const label_map = {
  counts: 'Expression',
  ann: 'Metabolism',
  dummy: 'Signalling'
}
const state_map = {
  counts: 'krona',
  ann: 'chord',
  dummy: 'chord'
}

const make_ann_counts = (index, count_matrix) => {
  // basically this removes extra stuff, leaving just data needed for the annotation ring
  const counts_idx = index.slice(1, index.indexOf('gap_2'))
  const counts = counts_idx.map((e) => d3.sum(count_matrix[index.indexOf(e)]))
  return { ann_counts_idx: counts_idx, ann_counts: counts }
}

const OverviewSection = ({ id, index, counts }) => {
  const base_radius = 50
  const rad_step = 10
  const width = 125
  const height = 125

  const ref = useRef<SVGSVGElement>(null)

  const handleClick = () => {
    useAppStore.setState({ mainState: state_map[id] })
  }

  useEffect(() => {
    console.log(`drawing overview ${id}`, index, counts)
    const arc = d3
      .arc()
      .innerRadius(base_radius)
      .outerRadius(base_radius + rad_step)

    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()
    svg
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', [-width / 2, -height / 2, width, height])
      .attr('style', 'max-width: 100%; height: auto; font: 10px sans-serif black; z-index: 10;')

    const data = index.map((e, i) => ({ id: e, value: counts[i] }))
    const pie = d3.pie().value((d) => d.value)
    const colors = d3.scaleOrdinal(
      index,
      index.map((_, i, arr) => get_color(i, arr.length))
    )

    const nodes = svg.append('g').selectAll().data(pie(data)).join('g')

    nodes
      .append('path') // draw arc
      .attr('fill', (d) => colors(d.data.id))
      .attr('d', arc)
      .attr('stroke', 'black')
      .append('title')
      .text((d) => d.data.id)
  }, [])

  return (
    <div className="overview-parent" id={`overview-${id}-parent`} onClick={handleClick}>
      <div id={`overview-${id}`}>
        <svg width={width} height={height} ref={ref} />
      </div>
      <span className="overview-label bold">{label_map[id]}</span>
    </div>
  )
}

const Overview = () => {
  const counts_data = useAppStore((state) => state.parsed_counts_data)
  const parsed_data = useAppStore((state) => state.parsed_data)
  const krona_data = useAppStore((state) => state.krona_data)
  const dummy_idx = ['g1', 'g2', 'g3', 'g4', 'g5']
  const dummy_counts = [5, 17, 22, 8, 11]

  let counts_idx, counts, ann_counts_idx, ann_counts
  if (!_.isEmpty(parsed_data)) {
    const { outer_count_matrix, outer_matrix_index } = parsed_data
    const tmp = make_ann_counts(outer_matrix_index, outer_count_matrix)
    ann_counts_idx = tmp.ann_counts_idx
    ann_counts = tmp.ann_counts
  }
  if (!_.isEmpty(counts_data)) {
    counts_idx = counts_data.counts_idx
    counts = counts_data.counts
  }
  const ready = counts_idx && ann_counts_idx && !_.isEmpty(krona_data)
  return (
    <div id="overview-container">
      {ready && <OverviewSection id="counts" index={counts_idx} counts={counts} />}
      {ready && <OverviewSection id="ann" index={ann_counts_idx} counts={ann_counts} />}
      {ready && <OverviewSection index={dummy_idx} id="dummy" counts={dummy_counts} />}
    </div>
  )
}

export default Overview
