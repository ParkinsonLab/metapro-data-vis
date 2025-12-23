import { create } from 'zustand'

// Define your store state interface
interface AppState {
  // Example state properties - customize based on your needs
  data: Array<object> | null
  ec: Array<object> | null
  parsed_data: any | null
  parsed_counts_data: any | null
  isLoading: boolean
  selectedFile: File | null
  selected_ann_cat: number
  selected_pathway : number
  selected_annotations: string[]
  mainState: 'upload' | 'chord' | 'network' | 'graph' | 'overview'
  tax_rank: 'kingdom' | 'phylum' | 'family' | 'class' | 'order' | 'genus'
  ann_rank: 'pathway' | 'superpathway'
  // Add more state properties as needed
}

export const useAppStore = create<AppState>((set) => ({
  data: null,
  ec: null,
  parsed_data: null,
  parsed_counts_data: null,
  isLoading: false,
  selectedFile: null,
  selected_ann_cat: 0,
  selected_pathway: 0,
  selected_annotations: [],
  mainState: 'upload',
  tax_rank: 'phylum',
  ann_rank: 'superpathway',
  setData: (data) => set({ data }),
  setEC: (ec) => set({ ec }),
  setLoading: (isLoading) => set({ isLoading }),
  setSelectedFile: (selectedFile) => set({ selectedFile }),
  setMainState: (mainState) => set({ mainState }),
}))