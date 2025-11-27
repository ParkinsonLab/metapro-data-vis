import { create } from 'zustand'

// Define your store state interface
interface AppState {
  // Example state properties - customize based on your needs
  data: Array<object> | null
  ec: Array<object> | null
  parsed_data: any | null
  isLoading: boolean
  selectedFile: File | null
  mainState: 'upload' | 'chord' | 'network' | 'plot'
  // Add more state properties as needed
}

export const useAppStore = create<AppState>((set) => ({
  data: null,
  ec: null,
  parsed_data: null,
  isLoading: false,
  selectedFile: null,
  mainState: 'upload',
  setData: (data) => set({ data }),
  setEC: (ec) => set({ ec }),
  setLoading: (isLoading) => set({ isLoading }),
  setSelectedFile: (selectedFile) => set({ selectedFile }),
  setMainState: (mainState) => set({ mainState }),
}))