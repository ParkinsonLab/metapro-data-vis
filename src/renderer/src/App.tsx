import Upload from './components/Upload'
import Chord from './components/Chord'
import Network from './components/Network'
import Graph from './components/Graph'
import Overview from './components/Overview'
import Krona from './components/Krona'
import { useAppStore } from './store/AppStore'
import { useEffect, useState } from 'react'
import { Oval } from 'react-loader-spinner'
import './App.css'

const channel_handlers = {
  load: (data) => {
    console.log(`adding ${data}`)
    useAppStore.setState((state) => ({
      file_list: [...(state.file_list || []), data]
    }))
  },
  load_test: (data) => {
    console.log(`adding ${data}`)
    useAppStore.setState((state) => ({
      file_list: [...(state.file_list || []), ...data],
      selected_file_list: data.slice(2)
    }))
  },
  overview: (data) => {
    useAppStore.setState({ overview_data: data })
  },
  krona: (data) => {
    useAppStore.setState({ krona_data: data })
  },
  chord: (data) => {
    useAppStore.setState({ chord_data: data })
  },
  network: (data) => {
    useAppStore.setState({ network_data: data })
  }
}

const register_handlers = () => {
  for (const channel in channel_handlers) {
    window.electron.ipcRenderer.on(`response-${channel}`, (_, data) => {
      channel_handlers[channel](data)
    })
  }
}

const NavBar = () => {
  const state_map = {
    'nav-upload': 'upload',
    'nav-chord': 'chord',
    'nav-network': 'network',
    'nav-graph': 'graph',
    'nav-overview': 'overview',
    'nav-krona': 'krona'
  }

  const mainState = useAppStore((state) => state.mainState)

  const handleNavClick = (event: React.MouseEvent<HTMLDivElement>) => {
    useAppStore.setState({ mainState: state_map[event.currentTarget.id] })
  }

  return (
    <>
      <p id="title">Metapro Viz</p>
      <div id="nav-container">
        <div
          id="nav-upload"
          onClick={handleNavClick}
          className={mainState === state_map['nav-upload'] ? 'bold' : ''}
        >
          Upload
        </div>
        <div
          id="nav-overview"
          onClick={handleNavClick}
          className={mainState === state_map['nav-overview'] ? 'bold' : ''}
        >
          Overview
        </div>
        <div
          id="nav-krona"
          onClick={handleNavClick}
          className={mainState === state_map['nav-krona'] ? 'bold' : ''}
        >
          Krona
        </div>
        <div
          id="nav-chord"
          onClick={handleNavClick}
          className={mainState === state_map['nav-chord'] ? 'bold' : ''}
        >
          Chord
        </div>
        <div
          id="nav-network"
          onClick={handleNavClick}
          className={mainState === state_map['nav-network'] ? 'bold' : ''}
        >
          Network
        </div>
        <div
          id="nav-graph"
          onClick={handleNavClick}
          className={mainState === state_map['nav-graph'] ? 'bold' : ''}
        >
          Graph
        </div>
      </div>
    </>
  )
}

const LoadingLayer = () => {
  const handleClick = (event) => {
    event.stopPropagation()
  }
  return (
    <div id="loading-layer" onClick={handleClick}>
      <Oval
        visible={true}
        height="120"
        width="120"
        color="black"
        ariaLabel="oval-loading"
        wrapperClass=""
      />
    </div>
  )
}

const DataInfoBar = () => {
  const selected_file_list = useAppStore(state => state.selected_file_list)
  let text
  if (selected_file_list.length === 0){
    text = 'no data selected'
  } else {
    text = selected_file_list.join('vs')
  }
  return (
    <p>{text}</p>
  )
}

const App = (): React.JSX.Element => {
  // use the useStore hook to check the overall state of the app called appState. Depending on whether the state is
  // upload, chord, network, or plot, show the corresponding component.
  const mainState = useAppStore((state) => state.mainState)
  const isLoading = useAppStore((state) => state.isLoading)
  // const data = useAppStore((state) => state.data)
  // const ec = useAppStore((state) => state.ec)

  // // data reparse triggers
  // const selected_trank = useAppStore((state) => state.tax_rank)
  // const selected_arank = useAppStore((state) => state.ann_rank)
  // const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
  // const selected_taxon = useAppStore((state) => state.selected_taxon)

  console.log(mainState + ' from app')
  // useEffect(() => {
  //   if (data.length > 0 && ec.length > 0) {
  //     parse_data(data, ec, selected_trank, selected_arank, selected_ann_cat, selected_taxon)
  //   }
  // }, [data, ec, selected_trank, selected_arank, selected_ann_cat, selected_taxon])

  // register data response handlers once
  useEffect(() => {
    register_handlers()
    window.electron.ipcRenderer.send('request-handshake')
  }, [])

  return (
    <>
      <NavBar />
      <DataInfoBar />
      {isLoading && <LoadingLayer />}
      <div id="main-container">
        {mainState === 'upload' && <Upload />}
        {/* {mainState === 'overview' && <Overview />} */}
        {mainState === 'chord' && <Chord />}
        {/* {mainState === 'network' && <Network />}
        {mainState === 'graph' && <Graph />}
        {mainState === 'krona' && <Krona />} */}
      </div>
    </>
  )
}

export default App
