import _ from 'lodash'
import { useAppStore } from "@renderer/store/AppStore";
import * as d3 from "d3";
import { useState, useEffect, useRef } from "react";

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
    const annotation_index = data_matrix_index.filter(e => annotation_checker(e))
    const tax_idx_start = data_matrix_index.indexOf('gap_2') + 1
    const tax_idx_end = data_matrix_index.indexOf('gap_3')
    const taxonomy_index = data_matrix_index.slice(tax_idx_start, tax_idx_end)
    const t_1 = data_matrix.filter((_, i) => annotation_checker(data_matrix_index[i]))
    const t_2 = t_1.map(e => e.slice(tax_idx_start, tax_idx_end))
    return {
        subset_data_matrix : t_2,
        annotation_index,
        taxonomy_index,
    }

}

const Network = (): React.JSX.Element => {

    const parsed_data = useAppStore(state => state.parsed_data)
    const selected_annotations = useAppStore(state => state.selected_annotations)
    const selected_ann_cat_idx = useAppStore(state => state.selected_ann_cat)
    const ref = useRef<SVGSVGElement>(null);
    const [placed_nodes, set_placed_nodes] = useState()

    if (parsed_data == null || _.isEmpty(parsed_data)) {
        return <div></div>
    }
    // we're displaying one super-pathway
    // TODO: change to a state passed from chord
    const width = 900
    const height = 550
    const max_title = 7
    const {
        inner_count_matrix, inner_matrix_index, outer_count_matrix, outer_matrix_index,
        colors, taxonomy_mapper, annotation_mapper
    } = parsed_data
    const selected_ann_cat = outer_matrix_index[selected_ann_cat_idx + 1]
    const {
        subset_data_matrix, annotation_index, taxonomy_index
    } = subset_data(inner_count_matrix, inner_matrix_index, e => annotation_mapper(e) === selected_ann_cat)
    
    // this gets all the annotation under the selected category
    const node_names = inner_matrix_index.slice(
        inner_matrix_index.indexOf('gap_1') + 1,
        inner_matrix_index.indexOf('gap_2')
    ).filter(d => annotation_mapper(d) === selected_ann_cat)

    const handle_node_click = (event, d) => {
        if (selected_annotations.includes(d.id)) {
            useAppStore.setState({selected_annotations: _.without(selected_annotations, d.id)})
        } else {
            useAppStore.setState({selected_annotations: [...selected_annotations, d.id]})
        }
        
    }

    // set data load callback
    const draw_network = (data) => {
        console.log('drawing network')
        console.log(data)
        if (!data) return

        const {grouped_nodes, edges} = data
        const nodes = get_nodes(grouped_nodes, width, height)
        const links = get_links(edges, nodes)
        const svg = d3.select(ref.current)
        svg.selectAll("*").remove()
        svg.attr("width", width)
            .attr("height", height)
            .attr("viewBox", [-width / 2, -height / 2, width, height])
            .attr("style", "max-width: 100%; height: auto;")

        // gradient
        const defs = svg.append("defs")
        const v_min = 5
        nodes.forEach((e) => {
            const d_row = subset_data_matrix[annotation_index.indexOf(e.id)]
            const v_sum = d3.sum(d_row)
            const grad_data = d_row.reduce((acc, e, i) => {
                const e2 = e / v_sum * 100
                if (e2 >= v_min) {
                    const start_val = acc.length === 0 ? 0 : acc[acc.length-1].value
                    return _.concat(acc, [{
                        id: taxonomy_index[i],
                        value: start_val  // not if empty
                    }, {
                        id: taxonomy_index[i],
                        value: start_val + e2 - (v_min / 100)
                    }]) // this makes e2 a running sum
                }
                return acc
            }, [])
            if (
                grad_data.length === 0 ||
                grad_data[grad_data.length-1].value < 100
            ) grad_data.push({id: 'grey', value: 100}) // fill remainder with grey

            const grad = defs
                .append('linearGradient')
                .attr("id", e.id)
                .attr("x1", 0).attr("x2", 0).attr("y1", 0).attr("y2", 1)
            grad.selectAll('stop').data(grad_data).join("stop")
                .attr("offset", d => `${d.value}%`)
                .attr("stop-color", d => colors[d.id] || `hsl(50 0 50)`)
        })
       
            // links
        const link_selection = svg.append("g")
            .selectAll("line")
            .data(links)
            .join("line")
            .attr("stroke-width", 1)
            .attr("stroke", "white")
            .attr("x1", d => d.source.cx)
            .attr("y1", d => d.source.cy)
            .attr("x2", d => d.target.cx)
            .attr("y2", d => d.target.cy)
            
        const node_selection = svg.append("g")
            .attr("stroke-width", 1)
            .selectAll()
            .data(nodes)
            .join("circle")
        
        node_selection
            .attr("r", d => d.size)
            .attr("fill", d => `url(#${d.id})`)
            .attr("cx", d => d.cx)
            .attr("cy", d => d.cy)
            .attr("stroke", d => selected_annotations.includes(d.id) ? 'blue' : 'white')
            .on('click', handle_node_click)

        node_selection.append("title")
            .text(d => d.id)
        
        // group titles
        svg.append("g")
            .selectAll("text")
            .data(nodes.filter(d => d.title))
            .join("text")
            .attr("x", d => d.cx)
            .attr("y", d => d.cy - (d.cy + height / 2) / y_top_margin_coef)
            .attr("transform", d => `rotate(45, ${d.cx}, ${d.cy - (d.cy + height / 2) / y_top_margin_coef})`)
            .attr("text-anchor", "end")
            .attr("class", "network-group-label")
            .text(d => d.title.length < max_title ? d.title : d.title.substring(0, max_title) + '...')
            .append('title')
            .text(d => d.title)
    }

    const handle_data_load = (_event, data) => {
        set_placed_nodes(data)
    }

    useEffect(() => {
        if (selected_ann_cat && node_names) {
            console.log('place-nodes request')
            window.electron.ipcRenderer.once('placed-nodes', handle_data_load);
            window.electron.ipcRenderer.send('place-nodes', selected_ann_cat, node_names);
        }
    }, [selected_ann_cat_idx])

    useEffect(() => {
        if (placed_nodes) {
            draw_network(placed_nodes)
        }
    }, [placed_nodes, selected_annotations])

    return (<>
        <div className="bold" id="network-title">{"Superpathway: " + selected_ann_cat}</div>
        <svg width={width} height={height} id="network" ref={ref} />

    </>)
}

export default Network;