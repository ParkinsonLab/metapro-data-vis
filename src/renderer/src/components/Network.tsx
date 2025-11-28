import _ from 'lodash'
import { useAppStore } from "@renderer/store/AppStore";
import * as d3 from "d3";
import { useState, useEffect, useRef } from "react";

interface node {
    id: string; cx: number; cy: number;
}
interface link {
    source: node | undefined; target: node | undefined; // should raise an error if actually undefined
}

const y_top_margin_coef = 2

// we use a different annotation mapper than chord
const ec_group_mapper = (name: string): string => name.substring(0, 3)

const group_node_names = (node_names: string[]): string[][] => {
    const t: Record<string, string[]> = node_names.reduce((acc: any, e: any) => {
        const group = ec_group_mapper(e)
        if (group in acc) {
            acc[group].push(e)
        } else {
            acc[group] = [e]
        }
        return acc
    }, {})
    return Object.values(t)
}

// currently this function also takes care of arrangement, which will probably be refactored out
// group the node names before calling this and next function
const get_nodes = (grouped_node_names: string[][], width: number, height: number): node[] => {
    const max_size = Math.max(...grouped_node_names.map(e => e.length))

    const x_step = width / (grouped_node_names.length + 2) // number of groups
    const y_step = height / (max_size + 2)
    
    const t = grouped_node_names.reduce((acc, g, i) => {
        return acc.concat(g.map((e, j) => {
            return {
                id: e,
                cx: (i + 1) * x_step - (width / 2 ),
                cy: (j + y_top_margin_coef) * y_step - (height / 2 ), // leave space up top for the ec
                size: Math.min(x_step, y_step) / 3,
            }
        }))
    }, [] as node[])
    return t
}
const get_links = (grouped_node_names: string[][], nodes: node[]): link[] => {
    // nodes which share the first three characters are mapped together
    const t_2: link[] = grouped_node_names.reduce(
        (acc: link[], e: string[]) => acc.concat(e.reduce(
            (acc: link[], e, i, arr) => {
                if (i === arr.length - 1) {
                    return acc // nothing for the last element
                }
                acc.push({
                    source: nodes.find(n => n.id === e), 
                    target: nodes.find(n => n.id === arr[i + 1]),
                })
            return acc
        }, [] as  link[]
    )), [] as link[]) // the last element is always null, but we're going to remove it
    return t_2
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
    const ref = useRef<SVGSVGElement>(null);

    if (parsed_data == null || _.isEmpty(parsed_data)) {
        return <div></div>
    }

    const {
        inner_count_matrix, inner_matrix_index, outer_count_matrix, outer_matrix_index,
        colors, taxonomy_mapper, annotation_mapper
    } = parsed_data

    // we're displaying one super-pathway
    // TODO: change to a state passed from chord
    const selected_ann_cat = outer_matrix_index[outer_matrix_index.indexOf('gap_1') + 1]
    const width = 800
    const height = 600

    // this gets all the annotation under the selected category
    const grouped_node_names = group_node_names(
        inner_matrix_index.slice(
            inner_matrix_index.indexOf('gap_1') + 1,
            inner_matrix_index.indexOf('gap_2')
        ).filter(d => annotation_mapper(d) === selected_ann_cat)
    )

    const nodes = get_nodes(grouped_node_names, width, height)
    const links = get_links(grouped_node_names, nodes)

    const {
        subset_data_matrix, annotation_index, taxonomy_index
    } = subset_data(inner_count_matrix, inner_matrix_index, e => annotation_mapper(e) === selected_ann_cat)

    useEffect(() => {
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
                    acc.push({
                        id: taxonomy_index[i],
                        value: e2 + (acc.length === 0 ? 0 : acc[acc.length-1].value)  // not if empty
                    }) // this makes e2 a running sum
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
            .attr("stroke", "white")
            .attr("stroke-width", 1)
            .selectAll()
            .data(nodes)
            .join("circle")
        
        node_selection
            .attr("r", d => d.size)
            .attr("fill", d => `url(#${d.id})`)
            .attr("cx", d => d.cx)
            .attr("cy", d => d.cy)

        node_selection.append("title")
            .text(d => d.id)
        
        // group titles
        svg.append("g")
            .selectAll("text")
            .data(nodes.filter(d => grouped_node_names.map(e => e[0]).includes(d.id)))
            .join("text")
            .attr("x", d => d.cx)
            .attr("y", d => d.cy - (d.cy + height / 2) / y_top_margin_coef)
            .attr("transform", d => `rotate(45, ${d.cx}, ${d.cy - (d.cy + height / 2) / y_top_margin_coef})`)
            .attr("text-anchor", "end")
            .attr("class", "network-group-label")
            .text(d => ec_group_mapper(d.id))

    }, [])


    return (<>
        <div className="bold" id="network-title">{"Superpathway: " + selected_ann_cat}</div>
        <svg width={width} height={height} id="network" ref={ref} />

    </>)
}

export default Network;