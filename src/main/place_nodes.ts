// function for placing nodes on a grid if we have a set of nodes and edges
import { join } from 'path'
import { readFileSync } from 'fs'
import { parse } from "csv-parse/sync"
import { sum } from "./utils"
import _ from "lodash"

interface Edge {
    source: string;
    target: string;
    pathway_number: string;
}
interface Coords {
    x: number;
    y: number;
}

const group_nodes = (nodes, group_dict) => {
    const acc = Object.fromEntries(
        _.uniq(Object.values(group_dict)).map(e => [e, new Array()])
    )
    acc['unknown']  = new Array()
    const t = nodes.reduce((acc, e) => {
        const g = group_dict[e]
        const k = g ? g : 'unknown'
        acc[k].push(e)
        return acc
    }, acc)

    return t
}

const estimate_height = (grouped_nodes: string[][]) => {
    const n_groups = grouped_nodes.length
    const group_sizes = grouped_nodes.map(e => e.length)

    // finds how many extra cols we're gonna need if we have this many rows
    const get_extra_cols = (h) => group_sizes.reduce((acc, n) => acc + Math.ceil(n / h), 0)
    
    let width = n_groups
    let height = Math.min(...group_sizes)
    let extra_columns = get_extra_cols(height)

    // attempt to make a square
    while (height <= (width + extra_columns)) {
        height += 1
        extra_columns = get_extra_cols(height)
    }
    return height
}

const find_next_node = (i: number, nodes: string[], edge_dict, coords: Coords[]) => {
    if (nodes[i] in edge_dict) { // if current node is part of an edge
        const candidates = edge_dict[nodes[i]].filter(e => !coords[nodes.indexOf(e)]) // connected but unplaced nodes
        if (candidates.length > 0) {
            for (const c of candidates) {
                const t = nodes.indexOf(c)
                if (t > 0) return t
            } // return the first edge candidate if it exists
        }
    }
    // if no edge candidates, go back to the master list and find the first unplaced node
    return coords.findIndex(e => !e)
}

const place_node = (i: number, height: number, nodes, edge_dict, coords, occupied): Coords => {
    if (i == 0) return {x: 0, y: 0}

    // check if the node if part of an edge
    if (nodes[i] in edge_dict) {
        const candidates = edge_dict[nodes[i]].filter(e => coords[nodes.indexOf(e)]) // connected but placed nodes
        if (candidates.length > 0) {
            const c = nodes.indexOf(candidates[0])
            let {x, y} = coords[c]
            y += 1
            // if we're at the bottom, we can only go towards the side
            if (y >= (height - 1)) {
                y -= 1
                x += 1
            }
            // continue towards the right if blocked
            while (occupied[y][x]) {
                x += 1
            }
            return {x, y}
        }
    }        
    // place de novo if not part of an edge
    // first find the column
    let x = -1
    let col;
    let col_sum;
    do {
        x += 1
        col = occupied.map(e => e[x])
        col_sum = sum(col)
    } while (col_sum >= height )
    const y = col.findIndex(e => e === 0) // the y is always the first available slot
    return {x, y}
}

const max_by_attr = (arr: Coords[], attr: string): number => {
    return Math.max(...arr.map(e => e[attr]))
}

// pushes subsequent groups to the right as needed
const apply_offset = (arr: Coords[][]): Coords[][] => {
    let cursor = 0
    const res = new Array(arr.length)
    for (let i = 0; i < arr.length; i++) {
        const t = arr[i].map(e => {
            return {...e, x: e.x + cursor, y: e.y,}
        })
        cursor = max_by_attr(t, 'x') + 1
        res[i] = t
    }
    return res
}

const assign_coords = (grouped_nodes, edge_dict) => {
     
    const assign_coords_group = (nodes, edge_dict, height) => {
        // for a single group
        // occupancy matrix
        const occupied = Array.from({ length: nodes.length }, () => Array(height).fill(0));
        // list of coords, also used to see if a node has been placed
        const coords = new Array(nodes.length)
        // next node to place
        let next_node = 0

        while (next_node > -1) {
            const t: Coords = place_node(next_node, height, nodes, edge_dict, coords, occupied)
            coords[next_node] = {
                id: nodes[next_node],
                x: t.x, y: t.y,
            }
            occupied[t.y][t.x] = 1

            // find the next node to place
            next_node = find_next_node(next_node, nodes, edge_dict, coords)
        }
        return coords
    }

    const keys = Object.keys(grouped_nodes)
    const v_list = keys.map(k => grouped_nodes[k])
    const height = estimate_height(v_list)

    // grouped_coords is a nested list, not a dict. The index is used as the key
    // it's aligned to keys
    const grouped_coords = apply_offset(
        v_list.map(v => assign_coords_group(v, edge_dict, height))
    )

    return Object.fromEntries(keys.map((k, i) => [k, grouped_coords[i]]))
}

const place_nodes = (pathway: string, nodes: string[]) => {
// nodes should be the grouped nodes
    const pathway_name_csv = parse(
        readFileSync(join(
            __dirname,
            join('../../resources/pathways', 'pathway_manifest.csv'),
        ), 'utf-8'), {
            columns: true,
            skip_empty_lines: true,
        }
    )
    const pathway_name_dict = Object.fromEntries(pathway_name_csv.map(e => ([e['number'], e['name']])))
    const f_path = join('../../resources/pathways', pathway.toLowerCase().replace(/ /g, '_') + '.csv')

    const csvData = readFileSync(join(__dirname, f_path), 'utf-8')
    const all_edges = (parse(csvData, {
        columns: true,
        skip_empty_lines: true,
    }) as Edge[]).filter((e: Edge) => (nodes.includes(e.source) && nodes.includes(e.target)))

    const edge_dict = all_edges.reduce((acc, e) => {
        if (e.source in acc) {
            acc[e.source].push(e.target)
        } else {
            acc[e.source] = [e.target]
        }
        if (e.target in acc) {
            acc[e.target].push(e.source)
        } else {
            acc[e.target] = [e.source]
        }
        return acc
    }, {})

    const pathway_dict = all_edges.reduce((acc, e) => {
        acc[e.source] = e.pathway_number
        acc[e.target] = e.pathway_number
        return acc
    }, {})

    const grouped_nodes = group_nodes(nodes, pathway_dict)

    // assign coords
    const coords = assign_coords(grouped_nodes, edge_dict)

    return {
        grouped_nodes: Object.fromEntries(
            Object.keys(coords).map(k => ([
                k in pathway_name_dict ? pathway_name_dict[k] : 'unknown',
                coords[k],
            ]))
        ),
        edges: all_edges,
    }
}


// debug code
const ec_list = readFileSync(
    join(__dirname, '../../resources/example_data/ecs.csv'),
    'utf-8'
).split('\n').filter(line => line.trim() !== '').map(d => d.slice(3))

const res = place_nodes(
    'Global and overview maps',
    ec_list
)
// console.log(res)
console.log('end!')

export default place_nodes