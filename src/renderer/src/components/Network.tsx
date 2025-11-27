import _ from 'lodash'
import { useAppStore } from "@renderer/store/AppStore";
import * as d3 from "d3";
import { useState, useEffect, useRef } from "react";

interface node {
    id: string; cx: number; cy: number;
}
interface link {
    source: string; target: string;
}

// we use a different annotation mapper than chord
const ec_group_mapper = (name: string) => name.substring(0, 3)

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
                cy: (j + 1) * y_step - (height / 2 ),
                size: Math.min(x_step, y_step) / 3,
            }
        }))
    }, [] as node[])
    return t
}
const get_links = (grouped_node_names: string[][]): link[] => {
    // nodes which share the first three characters are mapped together
    const t_2: link[] = grouped_node_names.reduce(
        (acc: link[], e: string[]) => acc.concat(e.reduce(
            (acc: {source: string; target: string;}[], e, i, arr) => {
                if (i === arr.length - 1) {
                    return acc // nothing for the last element
                }
                acc.push({
                    source: e, 
                    target: arr[i + 1],
                })
            return acc
        }, [] as  link[]
    ).slice(0, -1)), [] as link[]) // the last element is always null, but we're going to remove it
    return t_2
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
    const height = 640

    // this gets all the annotation under the selected category
    const grouped_node_names = group_node_names(
        inner_matrix_index.slice(
            inner_matrix_index.indexOf('gap_1') + 1,
            inner_matrix_index.indexOf('gap_2')
        ).filter(d => annotation_mapper(d) === selected_ann_cat)
    )

    const nodes = get_nodes(grouped_node_names, width, height)
    const links = get_links(grouped_node_names)

    useEffect(() => {
        const svg = d3.select(ref.current)
            .append("svg")
            .attr("width", width)
            .attr("height", height)
            .attr("viewBox", [-width / 2, -height / 2, width, height])
            .attr("style", "max-width: 100%; height: auto;");

        const node_selection = svg.append("g")
            .attr("stroke", "white")
            .attr("stroke-width", 1)
            .selectAll("circle")
            .data(nodes)
            .join("circle")
            .attr("r", d => d.size)
            .attr("fill", 'blue')
            .attr("cx", d => d.cx)
            .attr("cy", d => d.cy)
        node_selection.append("title")
            .text(d => d.id)
        
        // links
        svg.append("g")
            .attr("stroke", "white")
            .attr("stroke-opacity", 1)
            .selectAll("line")
            .data(links)
            .join("line")
            .attr("stroke-width", 1);
        

    }, [parsed_data])


    return (<>
        <div id="network-title">{selected_ann_cat}</div>
        <svg width={width} height={height} id="network" ref={ref} />

    </>)
}

export default Network;