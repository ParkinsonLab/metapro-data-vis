# Zustand Store Usage

## Basic Usage

```tsx
import { useStore } from './store/useStore'

function MyComponent() {
  // Access the entire store
  const { data, isLoading, setData, setLoading } = useStore()
  
  // Or use selectors for better performance (only re-renders when selected state changes)
  const data = useStore((state) => state.data)
  const setData = useStore((state) => state.setData)
  
  // Multiple selectors
  const { data, isLoading } = useStore((state) => ({
    data: state.data,
    isLoading: state.isLoading,
  }))
  
  return (
    <div>
      {isLoading && <p>Loading...</p>}
      {data && <pre>{JSON.stringify(data, null, 2)}</pre>}
      <button onClick={() => setData([1, 2, 3])}>Set Data</button>
    </div>
  )
}
```

## Example: Using in UploadFile Component

```tsx
import { useStore } from '../store/useStore'

function UploadFile() {
  const { selectedFile, setSelectedFile, setLoading, setError } = useStore()
  
  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setLoading(true)
      // Process file...
    }
  }
  
  return (
    <input type="file" onChange={handleFileChange} />
  )
}
```





