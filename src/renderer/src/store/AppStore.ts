import { create } from 'zustand'

// Define your store state interface
interface AppState {
  // Example state properties - customize based on your needs
  data: Array<object> | null
  ec: Array<object> | null
  parsed_data: any | null
  isLoading: boolean
  selectedFile: File | null
  selected_annotations: string[]
  mainState: 'upload' | 'chord' | 'network' | 'graph'
  // Add more state properties as needed
}

export const useAppStore = create<AppState>((set) => ({
  data: null,
  ec: null,
  parsed_data: null,
  isLoading: false,
  selectedFile: null,
  selected_annotations: ['1.1.1.100', '1.1.1.290', '1.1.98.6'],
  mainState: 'upload',
  setData: (data) => set({ data }),
  setEC: (ec) => set({ ec }),
  setLoading: (isLoading) => set({ isLoading }),
  setSelectedFile: (selectedFile) => set({ selectedFile }),
  setMainState: (mainState) => set({ mainState }),
}))