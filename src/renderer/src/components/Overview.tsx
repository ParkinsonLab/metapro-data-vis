//Overview graphic with bacterial cell

import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import * as d3 from 'd3'
import { useState, useEffect, useRef } from 'react'

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
  const { counts_data, ann_data, dummy_data } = useAppStore((state) => state.overview_data)
  const ready = !_.isEmpty(ann_data) && !_.isEmpty(counts_data) && !_.isEmpty(dummy_data)

  return (
    <div id="overview-container">
      {ready && (
        <OverviewSection id="counts" index={counts_data.index} counts={counts_data.counts} />
      )}
      {ready && <OverviewSection id="ann" index={ann_data.index} counts={ann_data.counts} />}
      {ready && <OverviewSection index={dummy_data.index} id="dummy" counts={dummy_data.counts} />}
    </div>
  )
}

export default Overview
