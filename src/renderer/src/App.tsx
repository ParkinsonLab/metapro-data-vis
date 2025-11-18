import Versions from './components/Versions'
import UploadFile from './components/Upload'
import electronLogo from './assets/electron.svg'
import { useState } from 'react'
import Upload from './components/Upload'
import Chord from './components/Chord'
import Network from './components/Network'
import Plot from './components/Plot'

type AppState = 'upload' | 'chord' | 'network' | 'plot'

function App(): React.JSX.Element {
  const ipcHandle = (): void => window.electron.ipcRenderer.send('ping')

  // use the useState hook to check the overall state of the app called appState. Depending on whether the state is
  // upload, chord, network, or plot, show the corresponding component.
  const [appState, setAppState] = useState<AppState>('upload')

  return (
    <>
      {appState === 'upload' && <Upload />}
      {appState === 'chord' && <Chord />}
      {appState === 'network' && <Network />}
      {appState === 'plot' && <Plot />}
    </>
  )
}

export default App
