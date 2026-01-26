import { create } from 'zustand'

// Define your store state interface
interface AppState {
  // Example state properties - customize based on your needs
  data: Array<object>
  ec: Array<object>
  parsed_data: any
  parsed_counts_data: any
  network_data: any
  krona_data: any
  isLoading: boolean
  selectedFile: File | null
  selected_ann_cat: number
  selected_pathway: string
  selected_annotations: string[]
  selected_taxon: number
  mainState: 'upload' | 'chord' | 'network' | 'graph' | 'overview' | 'krona'
  tax_rank: 'kingdom' | 'phylum' | 'family' | 'class' | 'order' | 'genus'
  ann_rank: 'pathway' | 'superpathway'
  // Add more state properties as needed
}

export const useAppStore = create<AppState>((set) => ({
  data: [],
  ec: [],
  parsed_data: [],
  parsed_counts_data: [],
  network_data: {},
  krona_data: {},
  isLoading: false,
  selectedFile: null,
  selected_ann_cat: 0,
  selected_pathway: '',
  selected_annotations: [],
  selected_taxon: 0,
  mainState: 'upload',
  tax_rank: 'phylum',
  ann_rank: 'superpathway',
  setData: (data) => set({ data }),
  setEC: (ec) => set({ ec }),
  setLoading: (isLoading) => set({ isLoading }),
  setSelectedFile: (selectedFile) => set({ selectedFile }),
  setMainState: (mainState) => set({ mainState }),
}))