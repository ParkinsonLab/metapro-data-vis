
// Chord-like diagram from plotly.js that plots classification on the left hand side and
// annotations on the right hand side

import { useAppStore } from "@renderer/store/AppStore";
import Plot from 'react-plotly.js';

// functions that preprocesses the data for the chord diagram
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
const domain_map = {
    "Methanosphaera stadtmanae": cats.firmicutes,
    "Methanobrevibacter smithii": cats.archaea,
}
const map_to_category = (name: string) => {
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
const to_chord_data = (data: any) => {

    const add_to_count_map = (acc: any, species: string, annotation: string, value: number) => {
        if (!acc[species]) {
            acc[species] = {};
        }
        if (!acc[species][annotation]) {
            acc[species][annotation] = 0;
        }
        acc[species][annotation] += value;
    }

    const count_map = data.reduce(
        (count_map: any, row: any) => {
            const ec_key = row['EC#'].split('.').slice(0, 2).join(".")
            Object.keys(row).forEach(key => {
                if (!key_cols.includes(key) && row[key] > 0) {
                    add_to_count_map(count_map, key, ec_key, row[key]);
                }
            });
            return count_map;
        },
        {}
    )

    // contains the annotation for each species-annotation combination
    const annotations = Object.keys(count_map).flatMap(
        (k: string) => Object.keys(count_map[k])
    )
    // contains the species for each species-annotation combination
    const species = Object.keys(count_map).flatMap(
        (k: string) => Object.keys(count_map[k]).map(() => k)
    )
    // contains flattened counts
    const counts = Object.keys(count_map).flatMap(
        (k: string) => Object.keys(count_map[k]).map((k2) => count_map[k][k2])
    )

    return {
        type: 'parcats',
        dimensions: [
            {
                label: "species",
                values: species,
            },
            {
                label: "annotations",
                values: annotations,
            },
        ],
        counts: counts,
    }
}

function Chord(): React.JSX.Element {
    
    const backToFileUpload = () => {
        useAppStore.setState({ mainState: 'upload' })
    }

    const data = useAppStore((state) => state.data)

    const trace = to_chord_data(data)

    return (
        <div>
            <Plot
                data={[trace]}
                layout={{width: 600}}
            />
            <button onClick={backToFileUpload}>Back to File Upload</button>
        </div>
        
    )

}

export default Chord;