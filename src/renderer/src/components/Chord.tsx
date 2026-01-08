
// Chord-like diagram from plotly.js that plots classification on the left hand side and
// annotations on the right hand side
import _ from 'lodash'
import { useAppStore } from "@renderer/store/AppStore";
import * as d3 from "d3";
import { useState, useEffect, useRef } from "react";
import parse_data from './parse';


const ChordSVG = () => {
    // Function to create the SVG element for the chord diagram
    const parsed_data = useAppStore(state => state.parsed_data)
    const selected_ann_cat = useAppStore(state => state.selected_ann_cat)

    const ref = useRef<SVGSVGElement>(null);

    const width = 900
    const height = 600
    const base_radius = Math.min(width, height) * 0.5 - 50 // the inner radius of the inner ring
    const rad_step = 20

    const draw_chord = () => {
        const { inner_count_matrix, inner_matrix_index, outer_count_matrix, outer_matrix_index, colors } = parsed_data

        const gaps = ['gap_1', 'gap_2', 'gap_3']
        const outer_gap_idc = gaps.map(e => outer_matrix_index.indexOf(e))
    
        const handle_arc_click = (event, d) => {
            const new_idx = d.index - 1
            if (new_idx < outer_gap_idc[1] - 1 && new_idx !== selected_ann_cat) {
                console.log('set selected_ann_cat to ' + new_idx)
                useAppStore.setState({ selected_ann_cat: new_idx, selected_annotations: [] }) // adjusted to -1 because 0th element is gap_0
            }
        }

        const inner_arc = d3.arc()
        .innerRadius(base_radius)
        .outerRadius(base_radius + rad_step)

        const outer_arc = d3.arc()
            .innerRadius(base_radius + rad_step * 2)
            .outerRadius(base_radius + rad_step * 3)

        const ribbon = d3.ribbon()
            .radius(base_radius);

        const svg = d3.select(ref.current)
        svg.selectAll("*").remove()
        svg.attr("width", width)
            .attr("height", height)
            .attr("viewBox", [-width / 2, -height / 2, width, height])
            .attr("style", "max-width: 100%; height: auto; font: 10px sans-serif white;");

        const inner_chords = d3.chord().padAngle(0).sortSubgroups(d3.descending)(inner_count_matrix);
        const outer_chords = d3.chord().padAngle(0).sortSubgroups(d3.descending)(outer_count_matrix);

        const get_group_label = (d) => ([{
            value: outer_matrix_index[d.index],
            angle: d.startAngle + (d.endAngle - d.startAngle) / 2,
            size: d.value,
        }])

        // outer arc
        const label_threshold = d3.sum(outer_count_matrix.flat()) / 800
        const outer_nodes = svg.append("g").selectAll()
            .data(outer_chords.groups.filter(d => !gaps.map(
                e => outer_matrix_index.indexOf(e)
            ).includes(d.index)))
            .join("g")
        outer_nodes.append("path") // draw arc
            .attr("fill", d => colors[outer_matrix_index[d.index]])
            .attr("d", outer_arc)
            .attr("stroke", d => d.index - 1 === selected_ann_cat ? 'blue' : 'white') // adjusted to -1 because first element is gap_1
            .on('click', handle_arc_click)
        outer_nodes.append("title")  // mouseover text
            .text(d => `${outer_matrix_index[d.index]} [${Math.trunc(d.value)}]`);
        
        const gap_regex = /^gap_[0-9]+$/
        const text_labels = outer_nodes.append("g")
            .selectAll()
            .data(get_group_label)
            .join("g")
            .attr("transform", d => `rotate(${d.angle * 180 / Math.PI - 90}) translate(${base_radius + rad_step * 3},0)`)
        text_labels
            .filter(d => !(gap_regex.test(d.value) || d.size < label_threshold))
            .append("text")
            .attr("x", 8)
            .attr("dy", "3px")
            .attr("transform", d => d.angle > Math.PI ? "rotate(180) translate(-16)" : null)
            .attr("text-anchor", d => d.angle > Math.PI ? "end" : null)
            .attr("class", "chord-label")
            .text(d => d.value.length > 10 ? d.value.substring(0, 7) + '...' : d.value)

        // inner arc
        svg.append("g").selectAll()
            .data(inner_chords.groups.filter(d => !gaps.map(
                e => inner_matrix_index.indexOf(e)
            ).includes(d.index)))
            .join("g")
            .append("path")
            .attr("fill", d => colors[inner_matrix_index[d.index]])
            .attr("d", inner_arc)
            .append("title")
            .text(d => `${inner_matrix_index[d.index]} [${Math.trunc(d.value)}]`);

        svg.append("g").selectAll()
            .data(inner_chords.filter(d => d.source.index !== d.target.index))
            .attr("fill-opacity", 0.7)
            .join("path")
            .attr("d", ribbon)
            .attr("fill", d => colors[inner_matrix_index[d.target.index]])
            // .attr("stroke", "white")
            .append("title")
            .text(
                d => `${inner_matrix_index[d.target.index]} → ${inner_matrix_index[d.source.index]} [${Math.trunc(d.source.value)}]`
            );
    }

    useEffect(() => {
        if (parsed_data !== null && !_.isEmpty(parsed_data)) {
            draw_chord()
        }
    }, [parsed_data, selected_ann_cat])

    return <svg width={width} height={height} id="chord" ref={ref} />
}

const RankSelector = () => {
    const t_ranks = ['kingdom', 'phylum', 'class', 'order', 'family', 'genus']
    const a_ranks = ['pathway', 'superpathway']
    const selected_trank = useAppStore(state => state.tax_rank)
    const selected_arank = useAppStore(state => state.ann_rank)
    const data = useAppStore(state => state.data)
    const ec = useAppStore(state => state.ec)

    const handle_trank_update = (event) => {
        useAppStore.setState({ tax_rank: event.currentTarget.id })
    }
    const handle_arank_update = (event) => {
        useAppStore.setState({ ann_rank: event.currentTarget.id })
    }
    const t_elements = t_ranks.map(e => (
        <span
            className={
                `${e === selected_trank ? 'bold' : ''}`
            } onClick={handle_trank_update} key={e} id={e}
        >{e}</span>
    ))
    const a_elements = a_ranks.map(e => (
        <span
            className={
                `${e === selected_arank ? 'bold' : ''}`
            } onClick={handle_arank_update} key={e} id={e}
        >{e}</span>
    ))

    useEffect(() => {
        if(data && ec && selected_trank && selected_arank) {
            parse_data(data, ec, selected_trank, selected_arank)
        }
    }, [data, ec, selected_trank, selected_arank])

    return (
        <div id="chord-top-bar">
            <div className='sub-selector-container'>
                { t_elements }
            </div>
            <div className='sub-selector-container'>
                { a_elements }
            </div>
        </div>

    )
}

const Chord = (): React.JSX.Element => {

    return (
        <div id="chord-container">
            <RankSelector />
            <ChordSVG />
        </div>

    )

}

export default Chord;