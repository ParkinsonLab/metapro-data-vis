// Chord-like diagram from plotly.js that plots classification on the left hand side and
// annotations on the right hand side
import _ from 'lodash'
import { useAppStore } from '@renderer/store/AppStore'
import * as d3 from 'd3'
import { useCallback, useEffect, useRef } from 'react'
import { request } from '../api'
import {
  isFilterActive,
  toApiFilter,
} from '../chordFilters'

//global
const t_ranks = ['kingdom', 'phylum', 'class', 'order', 'family', 'genus']
const a_ranks = ['pathway', 'superpathway']

const ChordSVG = () => {
  const chord_data = useAppStore((state) => state.chord_data)
  const ref = useRef<SVGSVGElement>(null)

  const width = 900
  const height = 600
  const base_radius = Math.min(width, height) * 0.5 - 50 // the inner radius of the inner ring
  const rad_step = 20

  const draw_chord = useCallback(() => {
    const {
      count_matrix,
      index,
      colors
    } = chord_data

    if (!Array.isArray(index) || !Array.isArray(count_matrix)) {
      console.error('[Chord] expected chord_data { count_matrix, index, colors }', chord_data)
      return
    }

    const { selected_ann_cat, selected_taxon, tax_rank, ann_rank } = useAppStore.getState()
    const ann_name = isFilterActive(selected_ann_cat) ? selected_ann_cat.name : ''
    const tax_name = isFilterActive(selected_taxon) ? selected_taxon.name : ''

    const gaps = ['gap_1', 'gap_2', 'gap_3']
    const outer_gap_idc = gaps.map((e) => index.indexOf(e))

    const handle_arc_click = (event, d) => {
      // d.index is the matrix row/col (0..n-1); matrix_labels[d.index] is the label string.
      const selected_name = String(index[d.index] ?? '')
      if (selected_name.substring(0, 3) === 'gap') return
      const state = useAppStore.getState()
      const ann = state.selected_ann_cat
      const tax = state.selected_taxon
      if (
        d.index > outer_gap_idc[0] &&
        d.index < outer_gap_idc[1] &&
        selected_name !== (isFilterActive(ann) ? ann.name : '')
      ) {
        useAppStore.setState({
          selected_ann_cat: { level: state.ann_rank, name: selected_name },
          selected_annotations: []
        })
      } else if (
        d.index > outer_gap_idc[1] &&
        d.index < outer_gap_idc[2] &&
        selected_name !== (isFilterActive(tax) ? tax.name : '')
      ) {
        const next_rank =
          state.tax_rank === t_ranks[t_ranks.length - 1]
            ? state.tax_rank
            : (t_ranks[t_ranks.indexOf(state.tax_rank) + 1] as typeof state.tax_rank)
        useAppStore.setState({
          selected_taxon: { level: state.tax_rank, name: selected_name },
          tax_rank: next_rank
        })
      }
    }

    const inner_arc = d3
      .arc()
      .innerRadius(base_radius)
      .outerRadius(base_radius + rad_step)

    const outer_arc = d3
      .arc()
      .innerRadius(base_radius + rad_step * 2)
      .outerRadius(base_radius + rad_step * 3)

    const ribbon = d3.ribbon().radius(base_radius)

    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()
    svg
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', [-width / 2, -height / 2, width, height])
      .attr('style', 'max-width: 100%; height: auto; font: 10px sans-serif black;')

    const inner_chords = d3.chord().padAngle(0).sortSubgroups(d3.descending)(count_matrix)
    const outer_chords = d3.chord().padAngle(0).sortSubgroups(d3.descending)(count_matrix)

    const get_group_label = (d) => [
      {
        value: index[d.index],
        angle: d.startAngle + (d.endAngle - d.startAngle) / 2,
        size: d.value
      }
    ]

    // outer arc
    const label_threshold = d3.sum(count_matrix.flat()) / 800
    const outer_nodes = svg
      .append('g')
      .selectAll()
      .data(
        outer_chords.groups.filter(
          (d) => !gaps.map((e) => index.indexOf(e)).includes(d.index)
        )
      )
      .join('g')
    outer_nodes
      .append('path') // draw arc
      .attr('fill', (d) => colors[index[d.index]])
      .attr('d', outer_arc)
      .attr('stroke', (d) => (index[d.index] === ann_name ? 'blue' : 'black'))
      .on('click', handle_arc_click)
    outer_nodes
      .append('title') // mouseover text
      .text((d) => `${index[d.index]} [${Math.trunc(d.value)}]`)

    const gap_regex = /^gap_[0-9]+$/
    const text_labels = outer_nodes
      .append('g')
      .selectAll()
      .data(get_group_label)
      .join('g')
      .attr(
        'transform',
        (d) =>
          `rotate(${(d.angle * 180) / Math.PI - 90}) translate(${base_radius + rad_step * 3},0)`
      )
    text_labels
      .filter((d) => !(gap_regex.test(d.value) || d.size < label_threshold))
      .append('text')
      .attr('x', 8)
      .attr('dy', '3px')
      .attr('transform', (d) => (d.angle > Math.PI ? 'rotate(180) translate(-16)' : null))
      .attr('text-anchor', (d) => (d.angle > Math.PI ? 'end' : null))
      .attr('class', 'chord-label')
      .text((d) => (d.value.length > 10 ? d.value.substring(0, 7) + '...' : d.value))

    // inner arc
    svg
      .append('g')
      .selectAll()
      .data(
        inner_chords.groups.filter(
          (d) => !gaps.map((e) => index.indexOf(e)).includes(d.index)
        )
      )
      .join('g')
      .append('path')
      .attr('fill', (d) => colors[index[d.index]])
      .attr('d', inner_arc)
      .append('title')
      .text((d) => `${index[d.index]} [${Math.trunc(d.value)}]`)

    svg
      .append('g')
      .selectAll()
      .data(inner_chords.filter((d) => d.source.index !== d.target.index))
      .attr('fill-opacity', 0.7)
      .join('path')
      .attr('d', ribbon)
      .attr('fill', (d) => colors[index[d.target.index]])
      // .attr("stroke", "black")
      .append('title')
      .text(
        (d) =>
          `${index[d.target.index]} → ${index[d.source.index]} [${Math.trunc(d.source.value)}]`
      )
  }, [chord_data])

  useEffect(() => {
    if (chord_data !== null && !_.isEmpty(chord_data)) {
      draw_chord()
    }
  }, [chord_data, draw_chord])

  return <svg width={width} height={height} id="chord" ref={ref} />
}

const RankSelector = () => {
  const selected_trank = useAppStore((state) => state.tax_rank)
  const selected_arank = useAppStore((state) => state.ann_rank)

  const handle_trank_update = (event) => {
    useAppStore.setState({ tax_rank: event.currentTarget.id })
  }
  const handle_arank_update = (event) => {
    useAppStore.setState({ ann_rank: event.currentTarget.id })
  }
  const t_elements = t_ranks.map((e) => (
    <span
      className={`${e === selected_trank ? 'bold' : ''}`}
      onClick={handle_trank_update}
      key={e}
      id={e}
    >
      {e}
    </span>
  ))
  const a_elements = a_ranks.map((e) => (
    <span
      className={`${e === selected_arank ? 'bold' : ''}`}
      onClick={handle_arank_update}
      key={e}
      id={e}
    >
      {e}
    </span>
  ))

  return (
    <div id="chord-top-bar">
      <div className="sub-selector-container">{t_elements}</div>
      <div className="sub-selector-container">{a_elements}</div>
    </div>
  )
}

const FilterChips = (): React.JSX.Element | null => {
  const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
  const selected_taxon = useAppStore((state) => state.selected_taxon)
  const ann_active = isFilterActive(selected_ann_cat)
  const tax_active = isFilterActive(selected_taxon)

  if (!ann_active && !tax_active) return null

  return (
    <div id="chord-filter-chips">
      {ann_active && (
        <span className="chord-filter-chip">
          Pathway: {selected_ann_cat.name} ({selected_ann_cat.level})
          <button
            type="button"
            aria-label="Clear pathway filter"
            onClick={() => useAppStore.setState({ selected_ann_cat: {}, selected_annotations: [] })}
          >
            ×
          </button>
        </span>
      )}
      {tax_active && (
        <span className="chord-filter-chip">
          Taxon: {selected_taxon.name} ({selected_taxon.level})
          <button
            type="button"
            aria-label="Clear taxon filter"
            onClick={() => useAppStore.setState({ selected_taxon: {} })}
          >
            ×
          </button>
        </span>
      )}
    </div>
  )
}

const Chord = (): React.JSX.Element => {
  const selected_file_list = useAppStore((state) => state.selected_file_list)
  const tax_rank = useAppStore((state) => state.tax_rank)
  const ann_rank = useAppStore((state) => state.ann_rank)
  const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
  const selected_taxon = useAppStore((state) => state.selected_taxon)

  useEffect(() => {
    if (selected_file_list.length === 0) return
    request('chord', {
      names: selected_file_list,
      tax_level: tax_rank,
      ann_level: ann_rank,
      selected_ann_cat: toApiFilter(selected_ann_cat),
      selected_taxon: toApiFilter(selected_taxon)
    })
  }, [selected_file_list, tax_rank, ann_rank, selected_ann_cat, selected_taxon])

  return (
    <div id="chord-container">
      <RankSelector />
      <FilterChips />
      <div id="chord-inner-container">
        <ChordSVG />
      </div>
    </div>
  )
}

export default Chord
