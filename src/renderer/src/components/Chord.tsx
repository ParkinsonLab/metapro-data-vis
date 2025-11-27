
// Chord-like diagram from plotly.js that plots classification on the left hand side and
// annotations on the right hand side

import { useAppStore } from "@renderer/store/AppStore";
import * as d3 from "d3";
import { useState, useEffect, useRef } from "react";
import _ from 'lodash'
// import Plot from 'react-plotly.js';

// maps a species name to luminosity (0-100)
// from the internet
const map_lum = (string) => {
    let hash = 0;
    for (const char of string) {
        hash = (hash << 5) - hash + char.charCodeAt(0);
        hash |= 0; // Constrain to 32bit integer
    }
    return Math.abs(Math.trunc(hash % 100)) 
};
const key_cols = [
    "EC#", "GeneID", "Length", "Reads", "RPKM"
]
const cats = {
    "bacteria": "Bacteria",
    "firmicutes": "Firmicutes",
    "actino": "Actinobacteria",
    "proteo": "Proteobacteria",
    "virus": "Viruses",
    "archaea": "Archaea",
}
const species_mapper = (name: string) => {
    if (Object.values(cats).includes(name)) {
        return name;
    }
    if (name in domain_map) {
        return domain_map[name];
    }
    // add additional name parsing here
    // the default is bacteria because it's the most common
    return cats.bacteria;
}
const get_cat_hue = (cat) => {
    return 360 / (Object.keys(cats).length + 1) * Object.values(cats).indexOf(cat)
}
const domain_map = {
    "Methanosphaera stadtmanae": cats.firmicutes,
    "Methanobrevibacter smithii": cats.archaea,
}
const sort_with_mapper = (a, b, mapper) => {
    const v =(
        Object.values(cats).indexOf(mapper(a)) - 
        Object.values(cats).indexOf(mapper(b))
    )
    // TODO: if equal, sort regularly
    if (v !== 0) return v
    if (a < b) return -1
    if (a > b) return 1
    return 0
}


// makes a count matrix from precalculated parameters and name mappers
// refactored out because we need to call it at least twice to make the inner and outer arcs
const make_count_matrix = (data, matrix_index, species_mapper, annotation_mapper) => {
    const add_to_count_map = (acc: any, species: string, annotation: string, value: number) => {
        const species_index = matrix_index.indexOf(species_mapper(species))
        const annotation_index = matrix_index.indexOf(annotation_mapper(annotation))
        if (species_index >= 0 && annotation_index >= 0){
            acc[species_index][annotation_index] += Number(value)
            acc[annotation_index][species_index] += Number(value);
        }
    }

    const count_matrix = data.reduce(
        (acc: any, row: any) => {
            const ec_key = row['EC#']
            Object.keys(row).forEach(key => {
                if (!key_cols.includes(key) && row[key] > 0) {
                    add_to_count_map(acc, key, ec_key, row[key]);
                }
            });
            return acc;
        }, Array.from({ length: matrix_index.length }, () =>
            Array(matrix_index.length).fill(0)
        )
    )

    //add filler
    const filler_nodes = ['gap_1', 'gap_2', 'gap_3']
    const flat_sum = d3.sum(count_matrix.flat())
    filler_nodes.forEach((name, idx) => {
        const i = matrix_index.indexOf(name)
        const div = idx === 1 ? 2 : 4
        count_matrix[i][i] = flat_sum / div
    })

    return count_matrix
}

const to_chord_data = (data: Array<Object>, ec_data: Array<Object>) => {
// functions that preprocesses the data for the chord diagram

    const ec_map = ec_data.reduce(
        (acc, row) => {
            Object.keys(row).forEach(
                (value) => { 
                    if(value && row[value]) acc[row[value].split(":")[1]] = value
                }
            )
            return acc
        }, {}
    )
    const annotation_mapper = (name: string) => {
        if (name in ec_map){
            return ec_map[name]
        }
        return null
    }

    // create count matrix for the outer ring
    // the difference is that this is aggregated
    const annotation_cats = [ ...new Set(Object.values(ec_map))]
    const species_cats = [ ...new Set(Object.values(cats))]
    const outer_matrix_index = ['gap_1'].concat(
        annotation_cats, // super pathways
        ['gap_2'], 
        species_cats, // domains
        ['gap_3']
    )
    const outer_count_matrix = make_count_matrix(
        data, outer_matrix_index, species_mapper, annotation_mapper
    )
    const outer_species_cm = species_cats.reduce((acc, e) => {
        acc[e] = `hsl(${get_cat_hue(e)} 75 50)`
        return acc
    }, {})
    const get_ann_cat_hue = (e) => Math.trunc(360 / (annotation_cats.length + 1) * annotation_cats.indexOf(e))
    const outer_annotations_cm = annotation_cats.reduce((acc, e) => {
        acc[e] = `hsl(${get_ann_cat_hue(e)} 75 50)`
        return acc
    }, {})

    // create count matrix for the inner ring
    // sort species by category
    const all_species = [ ...new Set(Object.keys(data[0]))].filter(
        e => !(key_cols.includes(e) || Object.values(cats).includes(e))
    ).slice().sort(
        (a, b) => sort_with_mapper(a, b, species_mapper)
    )
    const all_annotations = [ ...new Set(Object.keys(ec_map))].sort(
        (a, b) => sort_with_mapper(a, b, species_mapper)
    )
    const inner_matrix_index = ['gap_1'].concat(
        all_annotations, // all the ec numbers that are in the map (so excluding 0.0.0.0)
        ['gap_2'], 
        all_species, // all species
        ['gap_3']
    )
    const self_mapper = (a) => a
    const inner_count_matrix = make_count_matrix(
        data, inner_matrix_index, self_mapper, self_mapper
    )

    // inner color map
    const inner_species_cm = all_species.reduce((acc, e) => {
        acc[e] = `hsl(${get_cat_hue(species_mapper(e))} 75 ${map_lum(e)})`
        return acc
    }, {})
    const inner_annotation_cm = all_annotations.reduce((acc, e) => {
        acc[e] = `hsl(${get_ann_cat_hue(annotation_mapper(e))} 75 ${map_lum(e)})`
        return acc
    }, {})

    const colors = {
        ...inner_annotation_cm,
        ...inner_species_cm,
        ...outer_annotations_cm,
        ...outer_species_cm,
    }

    return {
        inner_count_matrix, inner_matrix_index, outer_count_matrix, outer_matrix_index, colors
    }
}

const ChordSVG = ({input}) => {
    // Function to create the SVG element for the chord diagram
    
    if (input == null || _.isEmpty(input)) {
        return <div></div>
    }
    const ref = useRef<SVGSVGElement>(null);

    const width = 800;
    const height = 640;
    const outerRadius = Math.min(width, height) * 0.5 - 30;
    const innerRadius = outerRadius - 20;
    const {inner_count_matrix, inner_matrix_index, outer_count_matrix, outer_matrix_index, colors} = input;
    
    const gaps = ['gap_1', 'gap_2', 'gap_3']
    
    useEffect( () => {
        // const sum = d3.sum(data.flat());

        // const chord = d3.chord()
        //     .padAngle(0)
        //     .sortSubgroups(d3.descending);

        const inner_arc = d3.arc()
            .innerRadius(innerRadius)
            .outerRadius(outerRadius);
        
        const outer_arc = d3.arc()
            .innerRadius(outerRadius + 20)
            .outerRadius(outerRadius + 40);

        const ribbon = d3.ribbon()
            .radius(innerRadius);

        const svg = d3.select(ref.current)
            .append("svg")
            .attr("width", width)
            .attr("height", height)
            .attr("viewBox", [-width / 2, -height / 2, width, height])
            .attr("style", "max-width: 100%; height: auto; font: 10px sans-serif white;");

        const inner_chords = d3.chord().padAngle(0).sortSubgroups(d3.descending)(inner_count_matrix);
        const outer_chords = d3.chord().padAngle(0).sortSubgroups(d3.descending)(outer_count_matrix);

        // outer arc
        svg.append("g")
            .selectAll()
            .data(outer_chords.groups.filter(d => !gaps.map(
                e => outer_matrix_index.indexOf(e)
            ).includes(d.index)))
            .join("g")
            .append("path")
            .attr("fill", d => colors[outer_matrix_index[d.index]])
            .attr("d", outer_arc)
            .attr("stroke", "white")
            .append("title")
            .text(d => `${d.value} ${outer_matrix_index[d.index]}`);
        
        // inner arc
        svg.append("g")
            .selectAll()
            .data(inner_chords.groups.filter(d => !gaps.map(
                e => inner_matrix_index.indexOf(e)
            ).includes(d.index)))
            .join("g")
            .append("path")
            .attr("fill", d => colors[inner_matrix_index[d.index]])
            .attr("d", inner_arc)
            .append("title")
            .text(d => `${d.value} ${inner_matrix_index[d.index]}`);

        svg.append("g")
            .attr("fill-opacity", 0.7)
            .selectAll()
            .data(inner_chords.filter(d => d.source.index !== d.target.index))
            .join("path")
            .attr("d", ribbon)
            .attr("fill", d => colors[inner_matrix_index[d.target.index]])
            // .attr("stroke", "white")
            .append("title")
            .text(
                d => `${d.source.value} ${inner_matrix_index[d.target.index]} → ${inner_matrix_index[d.source.index]}`
            );
    }, [input])
        
    return <svg width={width} height={height} id="chord" ref={ref} />
}

const Chord = (): React.JSX.Element => {

    const data = useAppStore((state) => state.data)
    const ec = useAppStore((state) => state.ec)
    const [parsed_data, set_parsed_data] = useState<any | null>(null)

    useEffect(() => {
        if (data && ec) {
            const tmp = to_chord_data(data, ec)
            console.log(tmp)
            set_parsed_data(tmp)
        }
    }, [data, ec])
    
    return (
        <div>
            <ChordSVG input={parsed_data} />
        </div>
        
    )

}

export default Chord;