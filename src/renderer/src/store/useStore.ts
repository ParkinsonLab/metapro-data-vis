import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

// Define your store state interface
interface StoreState {
  // Example state properties - customize based on your needs
  data: unknown[] | null
  isLoading: boolean
  error: string | null
  selectedFile: File | null
  // Add more state properties as needed
}

// Define your store actions interface
interface StoreActions {
  setData: (data: unknown[]) => void
  setLoading: (isLoading: boolean) => void
  setError: (error: string | null) => void
  setSelectedFile: (file: File | null) => void
  reset: () => void
  // Add more actions as needed
}

// Combine state and actions
type Store = StoreState & StoreActions

// Initial state
const initialState: StoreState = {
  data: null,
  isLoading: false,
  error: null,
  selectedFile: null,
}

// Create the store
export const useStore = create<Store>()(
  devtools(
    (set) => ({
      ...initialState,

      // Actions
      setData: (data) => set({ data, error: null }, false, 'setData'),
      setLoading: (isLoading) => set({ isLoading }, false, 'setLoading'),
      setError: (error) => set({ error }, false, 'setError'),
      setSelectedFile: (selectedFile) =>
        set({ selectedFile }, false, 'setSelectedFile'),
      reset: () => set(initialState, false, 'reset'),
    }),
    {
      name: 'metapro-data-vis-store', // Name for Redux DevTools
    }
  )
)

