// Ported from krona.js by Lucy Kang @ https://github.com/LucyK222/BCB330_Microbiome_Visualization

import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import * as d3 from 'd3'
import { useState, useEffect, useRef } from 'react'

const Krona = () => {
  const ref = useRef(null)
  const data = useAppStore((state) => state.krona_data)
  const { colors } = useAppStore((state) => state.parsed_data)
  const width = 600
  const height = width
  const radius = width / 6
  const label_max = 15

  useEffect(() => {
    console.log('drawing krona', data, colors)

    const svg = d3.select(ref.current).attr('viewBox', [-width / 2, -height / 2, width, width])
    svg.style('font', '8px sans-serif')
    svg.selectAll('*').remove()

    // const color = d3.scaleOrdinal(d3.quantize(d3.interpolateRainbow, data.children.length + 1))

    const hierarchy = d3
      .hierarchy(data)
      .sum((d) => d.value)
      .sort((a, b) => b.value - a.value)

    const root = d3.partition().size([2 * Math.PI, hierarchy.height + 1])(hierarchy)
    root.each((d) => (d.current = d))

    const arc = d3
      .arc()
      .startAngle((d) => d.x0)
      .endAngle((d) => d.x1)
      .padAngle((d) => Math.min((d.x1 - d.x0) / 2, 0.005))
      .padRadius(radius * 1.5)
      .innerRadius((d) => d.y0 * radius)
      .outerRadius((d) => Math.max(d.y0 * radius, d.y1 * radius - 1))

    const arcVisible = (d) => {
      return d.y1 <= 3 && d.y0 >= 1 && d.x1 > d.x0
    }

    const labelVisible = (d) => {
      return d.y1 <= 3 && d.y0 >= 1 && (d.y1 - d.y0) * (d.x1 - d.x0) > 0.05
    }

    const labelTransform = (d) => {
      const x = (((d.x0 + d.x1) / 2) * 180) / Math.PI
      const y = ((d.y0 + d.y1) / 2) * radius
      return `rotate(${x - 90}) translate(${y},0) rotate(${x < 180 ? 0 : 180})`
    }
    const path = svg
      .append('g')
      .selectAll('path')
      .data(root.descendants().slice(1))
      .join('path')
      .attr('fill', (d) => (colors[d.data.id] ? colors[d.data.id] : colors[d.parent.data.id]))
      .attr('fill-opacity', (d) => (arcVisible(d.current) ? (d.children ? 0.9 : 0.7) : 0))
      .attr('pointer-events', (d) => (arcVisible(d.current) ? 'auto' : 'none'))
      .attr('d', (d) => arc(d.current))

    path.append('title').text(
      (d) => `
        Taxon: ${d.data.id}
        Mean RPKM: ${d.value.toFixed(2)}
        Percentage: ${(d.data.percentage * 100).toFixed(2)}%
      `
    )
    const label = svg
      .append('g')
      .attr('pointer-events', 'none')
      .attr('text-anchor', 'middle')
      .style('user-select', 'none')
      .selectAll('text')
      .data(root.descendants().slice(1))
      .join('text')
      .attr('dy', '0.35em')
      .attr('fill-opacity', (d) => +labelVisible(d.current))
      .attr('transform', (d) => labelTransform(d.current))
      .text((d) =>
        d.data.label.length <= label_max ? d.data.label : d.data.label.slice(0, label_max) + '...'
      )
      .attr('fill', 'white')

    const parent = svg
      .append('circle')
      .datum(root)
      .attr('r', radius)
      .attr('fill', 'none')
      .attr('pointer-events', 'all')

    const clicked = (event, p) => {
      console.log('clicked', p)
      parent.datum(p.parent || root)

      root.each(
        (d) =>
          (d.target = {
            x0: Math.max(0, Math.min(1, (d.x0 - p.x0) / (p.x1 - p.x0))) * 2 * Math.PI,
            x1: Math.max(0, Math.min(1, (d.x1 - p.x0) / (p.x1 - p.x0))) * 2 * Math.PI,
            y0: Math.max(0, d.y0 - p.depth),
            y1: Math.max(0, d.y1 - p.depth)
          })
      )

      const t = svg.transition().duration(event.altKey ? 7500 : 750)

      path
        .transition(t)
        .tween('data', (d) => {
          const i = d3.interpolate(d.current, d.target)
          return (t) => (d.current = i(t))
        })
        .filter(function (d) {
          return +this.getAttribute('fill-opacity') || arcVisible(d.target)
        })
        .attr('fill-opacity', (d) => (arcVisible(d.target) ? (d.children ? 0.9 : 0.7) : 0))
        .attr('pointer-events', (d) => (arcVisible(d.target) ? 'auto' : 'none'))
        .attrTween('d', (d) => () => arc(d.current))

      label
        .filter(function (d) {
          return +this.getAttribute('fill-opacity') || labelVisible(d.target)
        })
        .transition(t)
        .attr('fill-opacity', (d) => +labelVisible(d.target))
        .attrTween('transform', (d) => () => labelTransform(d.current))
    }
    path
      .filter((d) => d.children)
      .style('cursor', 'pointer')
      .on('click', clicked)

    parent.on('click', clicked)
  }, [])

  return (
    <div>
      <svg id="krona" width={width} height={height} ref={ref} />
    </div>
  )
}

export default Krona
