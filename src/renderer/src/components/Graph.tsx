import Plot from 'react-plotly.js';
import _ from 'lodash'
import { useAppStore } from "@renderer/store/AppStore";
import { useState, useEffect, useRef } from "react";

type PlotTrace = {
    z: number[];
    x: number[];
    y: number[];
    line: {
        color: string;
        width: number;
    };
    mode: string;
    type: string;
    name: string;
};

function Graph(): React.JSX.Element {
    
    const parsed_data = useAppStore(state => state.parsed_data)
    const selected_annotations = useAppStore(state => state.selected_annotations)
    const [plot_data, set_plot_data] = useState<PlotTrace[]>([])
    const [plot_layout, set_plot_layout] = useState({})

    const trace_props = {
        mode: 'lines',
        type: 'scatter3d',
    }

    useEffect(() => {
        const {
            inner_count_matrix, inner_matrix_index, outer_count_matrix, outer_matrix_index,
            colors, taxonomy_mapper, annotation_mapper
        } = parsed_data
        
        const selected_idx = selected_annotations.map(e => inner_matrix_index.indexOf(e))
        const tax_idx_start = inner_matrix_index.indexOf('gap_2') + 1
        const tax_idx_end = inner_matrix_index.indexOf('gap_3')
        const tax_idc = [...Array(tax_idx_end - tax_idx_start).keys()].map(e => e + tax_idx_start)
        const subset_data = selected_idx.map(i => tax_idc.map(j => inner_count_matrix[i][j]))
        const tax_vals = Array.from(tax_idc.keys())
        const t_data = subset_data.map((e, i) => ({
            ...trace_props,
            x: Array(e.length).fill(i),
            y: tax_vals,
            z: e,
            name: selected_annotations[i],
            line: {
                color: colors[selected_annotations[i]],
                width: 2,
            }
        }))

        console.log(t_data)
        set_plot_data(t_data);

        const t_layout = {
            title: {
                text: 'RPKM for selected ECs',
                font: { color: 'white' }
            },
            scene: {
                xaxis: { 
                    title: { text: 'ECs', font: { color: 'white' } },
                    gridcolor: 'white',
                    range: [-1, subset_data.length],
                    tickvals : [...subset_data.keys()],
                    ticktext: selected_annotations,
                    ticklabelposition: 'outside bottom',
                    color: 'white',
                    tickfont: { color: 'white' },
                },
                yaxis: { 
                    title: { text: 'Toxonomy', font: { color: 'white' } },
                    tickmode: 'array',
                    tickvals: [], // too many, disabling for now
                    // tickvals: tax_vals,
                    // ticktext: tax_idc.map(k => inner_matrix_index[k].substring(0,7) + '...'), 
                    color: 'white',
                    tickfont: { color: 'white' },
                },
                zaxis: { 
                    title: { text: 'RPKM', font: { color: 'white' } },
                    color: 'white',
                    tickfont: { color: 'white' },
                },
            },
            paper_bgcolor: 'rgb(27, 27, 31)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            autosize: true,
            margin: { l: 0, r: 10, b: 10, t: 60, pad: 0 },
            width: 800,
            height: 500,
            legend: {
                x: 1.0,
                y: 0.5,
                xanchor: 'right',
                yanchor: 'bottom',
                font: { color: 'white' },
            },
        }
        console.log(t_layout)
        set_plot_layout(t_layout)
    }, [parsed_data])

    return (
        <div id="graph-container">
            <Plot
                data={plot_data}
                layout={plot_layout} 
            />
        </div>
    )
}

export default Graph;