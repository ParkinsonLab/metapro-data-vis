import { map_lum } from './util'
import _ from 'lodash'
import { useAppStore } from "@renderer/store/AppStore";
import * as d3 from "d3";

// file for the data parser
// cols from ec_rpkm which don't countain counts
const key_cols = [
    "EC#", "GeneID", "Length", "Reads", "RPKM"
]

// standardized names for taxonomy at the domain level
const tax_domains = {
    "bacteria": "Bacteria",
    "firmicutes": "Firmicutes",
    "actino": "Actinobacteria",
    "proteo": "Proteobacteria",
    "virus": "Viruses",
    "archaea": "Archaea",
}

// How species map to domains. Will need to fill this out more
const domain_map = {
    "Methanosphaera stadtmanae": tax_domains.firmicutes,
    "Methanobrevibacter smithii": tax_domains.archaea,
}

// maps taxonomic names to domains
const taxonomy_mapper = (name: string) => {
    if (Object.values(tax_domains).includes(name)) {
        return name;
    }
    if (name in domain_map) {
        return domain_map[name];
    }
    // add additional name parsing here
    // the default is bacteria because it's the most common
    return tax_domains.bacteria;
}

// helper function that performs two-level sorting, category first
const sort_by_category = (a, b, get_cat_idx: Function) => {
    // get_cat_idx(a) returns numerical index of the category a belongs to
    // sort by category first, then alphabetically if equal
    const m_a = get_cat_idx(a)
    const m_b = get_cat_idx(b)
    const v_a = m_a === m_b ? a : m_a;
    const v_b = m_a === m_b ? b : m_b;
    // TODO: if equal, sort regularly
    if (v_a < v_b) return -1
    if (v_a > v_b) return 1
    return 0
}

// makes a count matrix from precalculated parameters and name mappers
// refactored out because we need to call it at least twice to make the inner and outer arcs
const make_count_matrix = (data, matrix_index, species_mapper, annotation_mapper) => {
    const add_to_count_map = (acc: any, species: string, annotation: string, value: number) => {
        const species_index = matrix_index.indexOf(species_mapper(species))
        const annotation_index = matrix_index.indexOf(annotation_mapper(annotation))
        if (species_index >= 0 && annotation_index >= 0) {
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

// main data parsing function for the front end
// we should run this once to save time between tab switches
const parse_data = (data: Array<Object>, ec_data: Array<Object>) => {
    // functions that preprocesses the data for the chord diagram
    const ec_map = ec_data.reduce(
        (acc, row) => {
            Object.keys(row).forEach(
                (value) => {
                    if (value && row[value]) acc[row[value].split(":")[1]] = value
                }
            )
            return acc
        }, {}
    )
    const annotation_mapper = (name: string) => {
        if (name in ec_map) {
            return ec_map[name]
        }
        return null
    }

    // create count matrix for the outer ring
    // the difference is that this is aggregated
    const annotation_cats = [...new Set(Object.values(ec_map))]
    const tax_cats = [...new Set(Object.values(tax_domains))] // taxonomic categories
    const get_cat_hue = (e) => Math.trunc(360 / (tax_cats.length + 1) * tax_cats.indexOf(e))
    const get_ann_cat_hue = (e) => Math.trunc(360 / (annotation_cats.length + 1) * annotation_cats.indexOf(e))

    const outer_matrix_index = ['gap_1'].concat(
        annotation_cats, // super pathways
        ['gap_2'],
        tax_cats, // domains
        ['gap_3']
    )
    const outer_count_matrix = make_count_matrix(
        data, outer_matrix_index, taxonomy_mapper, annotation_mapper
    )
    const outer_species_cm = tax_cats.reduce((acc, e) => {
        acc[e] = `hsl(${get_cat_hue(e)} 75 50)`
        return acc
    }, {})
    const outer_annotations_cm = annotation_cats.reduce((acc, e) => {
        acc[e] = `hsl(${get_ann_cat_hue(e)} 75 50)`
        return acc
    }, {})

    // create count matrix for the inner ring
    // sort species by category
    const all_species = [...new Set(Object.keys(data[0]))].filter(
        e => !(key_cols.includes(e) || Object.values(tax_domains).includes(e))
    ).slice().sort(
        (a, b) => sort_by_category(a, b, name => tax_cats.indexOf(taxonomy_mapper(name)))
    )
    const all_annotations = [...new Set(Object.keys(ec_map))].sort(
        (a, b) => sort_by_category(a, b, name => annotation_cats.indexOf(annotation_mapper(name)))
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

    // trim inner matrix
    const idx_to_keep = inner_count_matrix.reduce((acc, e, i) => {
        if(d3.sum(e) > 0) acc.push(i)
        return acc
    }, [])
    const trimmed_inner_count_matrix = idx_to_keep.map(
        e => idx_to_keep.map(e2 => inner_count_matrix[e][e2])
    )
    const trimmed_inner_matrix_idx = idx_to_keep.map(
        e => inner_matrix_index[e]
    )

    // inner color map
    const inner_species_cm = all_species.reduce((acc, e) => {
        acc[e] = `hsl(${get_cat_hue(taxonomy_mapper(e))} 75 ${map_lum(e)})`
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

    useAppStore.setState({
        parsed_data: {
            inner_count_matrix: trimmed_inner_count_matrix, 
            inner_matrix_index: trimmed_inner_matrix_idx, 
            outer_count_matrix, outer_matrix_index, colors,
            taxonomy_mapper, annotation_mapper
        },
        mainState: 'chord', isLoading: false
    })
}

export default parse_data;