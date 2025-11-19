import { create } from 'zustand'

// Define your store state interface
interface AppState {
  // Example state properties - customize based on your needs
  data: object | null
  isLoading: boolean
  selectedFile: File | null
  mainState: 'upload' | 'chord' | 'network' | 'plot'
  // Add more state properties as needed
}

export const useAppStore = create<AppState>((set) => ({
  data: null,
  isLoading: false,
  selectedFile: null,
  mainState: 'upload',
  setData: (data) => set({ data }),
  setLoading: (isLoading) => set({ isLoading }),
  setSelectedFile: (selectedFile) => set({ selectedFile }),
  setMainState: (mainState) => set({ mainState }),
}))