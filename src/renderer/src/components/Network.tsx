import _ from 'lodash'
import { useAppStore } from "@renderer/store/AppStore";
import * as d3 from "d3";
import React, { useState, useEffect, useRef } from "react";
import { get_color } from './util';

interface node {
    id: string; cx: number; cy: number; title: string | null;
}
interface node_raw {
    id: string; x: number; y: number;
}
interface link {
    source: node | undefined; target: node | undefined; // should raise an error if actually undefined
}
interface link_raw {
    source: string; target: string;
}

const y_top_margin_coef = 4

// // we use a different annotation mapper than chord
// const ec_group_mapper = (name: string): string => name.substring(0, 3)

// const group_node_names = (node_names: string[]): string[][] => {
//     const t: Record<string, string[]> = node_names.reduce((acc: any, e: any) => {
//         const group = ec_group_mapper(e)
//         if (group in acc) {
//             acc[group].push(e)
//         } else {
//             acc[group] = [e]
//         }
//         return acc
//     }, {})
//     return Object.values(t)
// }


// currently this function also takes care of arrangement, which will probably be refactored out
// group the node names before calling this and next function
const get_nodes = (grouped_nodes: Record<string, node_raw[]>, width: number, height: number): node[] => {
    
    const n_vals = Object.values(grouped_nodes).flat()
    const max_x = Math.max(...(n_vals.map(e => e.x)))
    const max_y = Math.max(...(n_vals.map(e => e.y)))

    const x_step = width / (max_x + 4) // number of groups
    const y_step = height / (max_y + y_top_margin_coef + 4)
    
    const gk = Object.keys(grouped_nodes)
    const t = gk.reduce((acc, k) => {
        return acc.concat(grouped_nodes[k].map((e, i) => {
            return {
                id: e.id,
                cx: (e.x + 2) * x_step - (width / 2 ),
                cy: (e.y + y_top_margin_coef) * y_step - (height / 2 ), // leave space up top for the ec
                size: Math.min(x_step, y_step) / 3,
                title: i == 0 ? k : null // only add title to the first of the group
            }
        }))
    }, [] as node[])
    return t
}

const get_links = (edges_raw: link_raw[], nodes: node[]): link[] => {
    // nodes which share the first three characters are mapped together
    return edges_raw.map(
        e => ({
            source: nodes.find(n => n.id === e.source), 
            target: nodes.find(n => n.id === e.target),
        })
    )
}

// this needs the inner matrix and index
const subset_data = (data_matrix, data_matrix_index, annotation_checker) => {

    // rows only for annotations that pass the checker
    const ann_idx = data_matrix_index.filter(e => annotation_checker(e))
    const tax_idx_start = data_matrix_index.indexOf('gap_2') + 1
    const tax_idx_end = data_matrix_index.indexOf('gap_3')
    const tax_idx = data_matrix_index.slice(tax_idx_start, tax_idx_end)
    const t_1 = data_matrix.filter((_, i) => annotation_checker(data_matrix_index[i]))
    const t_2 = t_1.map(e => e.slice(tax_idx_start, tax_idx_end))
    return {
        data : t_2,
        ann_idx, // 1st dimension index
        tax_idx, // 2nd dimension index
    }
}

const condense_to_tax_group = (data_matrix, tax_index, tax_map) => {
    // condenses the 2nd dimension (taxonomy) to the group level, according to tax_map

    const tax_cats = _.uniq(Object.values(tax_map))
    return {
        data: data_matrix.map(
            e => e.reduce(
                (acc, e2, i) => {
                    acc[tax_cats.indexOf(tax_map[tax_index[i]])] += e2
                    return acc
                },
                tax_cats.map(_ => 0))
            ),
        tax_cats,
    }
}

const get_formatted_network_data = (parsed_data, network_data, pathway, ann_map, height, width) => {
    
    // add counts information to network_data
    // use datastore data

    const { inner_count_matrix, inner_matrix_index, colors, tax_mapping } = parsed_data
    const {
        data, ann_idx, tax_idx
    } = subset_data(inner_count_matrix, inner_matrix_index, e => ann_map[e] === pathway)
    
    const {
        data: condensed_data, tax_cats
    } = condense_to_tax_group(data, tax_idx, tax_mapping)

    const new_nodes = network_data.nodes.map(
        e => {
            return {
                ...e,
                x: e.y / 1200 * width - width / 3,
                y: e.x / 1000 * height - height / 2,
                values: (
                    ann_idx.includes(e.name) ?
                    condensed_data[ann_idx.indexOf(e.name)].map((e, i) => ({
                        id: tax_cats[i], value: e
                    })):
                    []
                )   
            }
        }
    )

    const new_edges = network_data.edges.map(
        e => ({
            source: _.find(new_nodes, e2 => e2.name === e.source),
            target: _.find(new_nodes, e2 => e2.name === e.target),
        })
    )

    const to_return = {
        nodes: new_nodes,
        edges: new_edges,
        colors: colors,
    }

    console.log(to_return)
    
    return to_return

}

const Pathway = ({ width, height, pathway, ann_map }): React.JSX.Element => {
    // Do not mount this component without checking that data exists
    // Check at parent level
    // Since this replaces the preview panel, network data should not be able to
    // change while this is mounted

    // set data load callback
    const max_label_length = 7
    const ref = useRef<SVGSVGElement>(null);
    const selected_annotations = useAppStore(state => state.selected_annotations)

    // reformat data
    const parsed_data = useAppStore(state => state.parsed_data)
    const network_data = useAppStore(state => state.network_data)

    // const handle_node_click = (event, d) => {
    //     if (selected_annotations.includes(d.id)) {
    //         useAppStore.setState({selected_annotations: _.without(selected_annotations, d.id)})
    //     } else {
    //         useAppStore.setState({selected_annotations: [...selected_annotations, d.id]})
    //     }
    // }

    useEffect(() => {
        console.log('drawing network')
        const plot_data = get_formatted_network_data(parsed_data, network_data, pathway, ann_map, height, width)

        const {nodes, edges, colors} = plot_data
        const svg = d3.select(ref.current)
        svg.selectAll("*").remove()
        svg.attr("width", width)
            .attr("height", height)
            .attr("viewBox", [-width / 2, -height / 2, width, height])
            .attr("style", "max-width: 100%; height: auto;")

        // links
        const link_selection = svg.append("g")
            .selectAll("line")
            .data(edges)
            .join("line")
            .attr("stroke-width", 1)
            .attr("stroke", "white")
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y)
            
        const node_selection = svg.append("g")
            .selectAll("g")
            .data(nodes)
            .join(enter => {
                const g = enter.append('g')
                g.each(function(d) {
                    // For each toy_data row, construct the arc pie pieces within this 'g'
                    const arc = d3.arc()
                        .innerRadius(10)
                        .outerRadius(12)
                    // d is an array; generate pie data manually
                    const pie = d3.pie().value(d2 => d2.value);
                    const pie_g = d3.select(this)
                    pie_g.attr('transform', `translate(${d.x}, ${d.y})`)
                    pie_g.selectAll('path')
                        .data(pie(d.values))
                        .join('path')
                        .attr('d', arc)
                        .attr('fill', d2 => (colors[d2.data.id]))
                    pie_g.append('path')
                    .attr('d', d2 => d2.type === 'circle' ? d3.symbol(d3.symbolCircle, 50)() : d3.symbol(d3.symbolSquare, 50)())
                    .attr('fill', 'white')
                    .append('title').text(d2 => d2.name)
                })
                return g
            })
        
        // node_selection
        //     .attr("r", d => d.size)
        //     .attr("fill", d => `url(#${d.id})`)
        //     .attr("cx", d => d.cx)
        //     .attr("cy", d => d.cy)
        //     .attr("stroke", d => selected_annotations.includes(d.id) ? 'blue' : 'white')

        // node_selection.append("title")
        //     .text(d => d.id)
        
        // // group titles
        // svg.append("g")
        //     .selectAll("text")
        //     .data(nodes.filter(d => d.title))
        //     .join("text")
        //     .attr("x", d => d.cx)
        //     .attr("y", d => d.cy - (d.cy + height / 2) / y_top_margin_coef)
        //     .attr("transform", d => `rotate(45, ${d.cx}, ${d.cy - (d.cy + height / 2) / y_top_margin_coef})`)
        //     .attr("text-anchor", "end")
        //     .attr("class", "network-group-label")
        //     .text(d => d.title.length < max_label_length ? d.title : d.title.substring(0, max_label_length) + '...')
        //     .append('title')
        //     .text(d => d.title)
    }, [])

    return (<>
        
        <svg width={width} height={height} id="network" ref={ref} />

    </>)
}

const PathwayPreview = ({height, width, pathway, ann_map}: {height: number, width: number, pathway: string, ann_map: Record<string, string>}): React.JSX.Element => {
    const ref = useRef<SVGSVGElement>(null)
    const base_radius = Math.min(height, width) * 0.3
    const rad_step = Math.ceil(base_radius * 0.2)
    const text_height = 25

    const parsed_data = useAppStore(state => state.parsed_data)
    const ec_data = useAppStore(state => state.ec)
    const { inner_count_matrix, inner_matrix_index, tax_mapping: tax_map, colors } = parsed_data
    const { data, ann_idx, tax_idx } = subset_data(inner_count_matrix, inner_matrix_index, e => ann_map[e] === pathway)
    const { data: condensed_data, tax_cats } = condense_to_tax_group(data, tax_idx, tax_map)
    const pie_data = tax_cats.map((e, i) => ({id: e, value: d3.sum(condensed_data.map(e2 => e2[i]))}))

    const handle_click = (event) => {
        console.log('handle click on preview')
        const pathway_id = _.find(ec_data, e => e.pathway_name === pathway)['pathway_id']
        useAppStore.setState({isLoading: true})
        window.electron.ipcRenderer.once('return-node-info', (_, data) => {
            console.log('network_data', data)
            useAppStore.setState({network_data: data, selected_pathway: pathway, isLoading: false, })
        })
        window.electron.ipcRenderer.send('request-node-info', pathway_id)
    }

    useEffect(() => {
        const arc = d3.arc()
        .innerRadius(base_radius)
        .outerRadius(base_radius + rad_step)

        const svg = d3.select(ref.current)
        svg.selectAll("*").remove()
        svg.attr("width", width)
            .attr("height", height - text_height)
            .attr("viewBox", [-width / 2, -height / 2, width, height])
            .attr("style", "font: 10px sans-serif white;")

        const pie = d3.pie().value(d => d.value)
        // node here isn't network nodes, it's the nodes of the arc for the pie
        const nodes = svg.append("g").selectAll()
            .data(pie(pie_data))
            .join("g")

        nodes.append("path") // draw arc
            .attr("fill", d => colors[d.data.id])
            .attr("d", arc)
            .attr("stroke", 'white')
            .append("title")
            .text(d => d.data.id)
    }, [])

    return (
        <div onClick={handle_click} className='pathway-preview-item' style={{height: height, width: width}}>
            <svg ref={ref} />
            <span className='pathway-preview-item-name'>{pathway}</span>
        </div>
    )
}

const PathwayPreviewContainer = ({height, width, superpathway, ann_map}) => {

    // prevent mounting of this element if parrsed_data is null at the parent level
    // here we assume that it has been loaded

    const pathways = _.uniq(Object.values(ann_map))
    const grid_size = Math.ceil(Math.sqrt(pathways.length))
    const c_width = width / grid_size
    const c_height = height / grid_size
    const elements = pathways.map(e => (
        <PathwayPreview
            height={c_height} width={c_width} pathway={e} ann_map={ann_map} key={e}
        />
    ))

    return (
        <div id="pathway-preview-outer-container">
            <div className="bold" id="network-title">{"Superpathway: " + superpathway}</div>
            <div id="pathway-preview-container">
                {elements}
            </div>
        </div>
        
    )
}

const Network = (): React.JSX.Element => {
    // parsed_data emptiness checks are done at the parent level

    const width = 900
    const height = 550

    const selected_pathway = useAppStore(state => state.selected_pathway)
    const network_data = useAppStore(state => state.network_data)
    const selected_ann_cat_idx = useAppStore(state => state.selected_ann_cat)
    const ec_data = useAppStore(state => state.ec)

    // Here we map to pathway level regardless of what was selected in the above
    const parsed_data = useAppStore(state => state.parsed_data)
    const { outer_matrix_index } = parsed_data
    const selected_ann_cat = outer_matrix_index[selected_ann_cat_idx + 1]
    const ann_map = Object.fromEntries(
        ec_data.filter(e => e['superpathway'] === selected_ann_cat).map(e => [e['ec'], e['pathway_name']])
    )

    return (
        <div>
            {
                selected_pathway && !_.isEmpty(network_data) ?
                (<div>
                    <button>Back</button>
                    <Pathway width={width} height={height} pathway={selected_pathway} ann_map={ann_map} />
                </div>) :
                <PathwayPreviewContainer 
                    width={width} height={height} superpathway={selected_ann_cat} ann_map={ann_map}
                />
            }
        </div>
    )


}

export default Network;