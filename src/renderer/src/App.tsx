import Upload from './components/Upload'
import Chord from './components/Chord'
import Network from './components/Network'
import Plot from './components/Plot'
import { useAppStore } from './store/AppStore'

function App(): React.JSX.Element {

  // use the useStore hook to check the overall state of the app called appState. Depending on whether the state is
  // upload, chord, network, or plot, show the corresponding component.
  const mainState = useAppStore((state) => state.mainState)

  return (
    <>
      {mainState === 'upload' && <Upload />}
      {mainState === 'chord' && <Chord />}
      {mainState === 'network' && <Network />}
      {mainState === 'plot' && <Plot />}
    </>
  )
}

export default App
