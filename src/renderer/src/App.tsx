import Upload from './components/Upload'
import Chord from './components/Chord'
import Network from './components/Network'
import Overview from './components/Overview'
import Krona from './components/Krona'
import Graph from './components/Graph'
import { useAppStore } from './store/AppStore'
import { type Channel, registerChannelHandler, request } from './api'
import { useEffect } from 'react'
import { Oval } from 'react-loader-spinner'
import './App.css'

const channel_handlers: Record<Channel, (value: unknown) => void> = {
  // initialize() returns 0 on success, 3 when the taxonomy DB cannot be opened.
  handshake: (value) => {
    useAppStore.setState({ db_ready: value === 0 })
    if (value !== 0) {
      useAppStore.setState({
        last_error:
          'Taxonomy database is unreachable (resources/db/taxonomy.db). Visualizations will not load until this is fixed.'
      })
    }
  },
  load: (value) => {
    const name = value as string
    useAppStore.setState((state) => ({
      file_list: [...(state.file_list || []), name]
    }))
  },
  load_test: (value) => {
    const names = value as string[]
    useAppStore.setState((state) => ({
      file_list: [...(state.file_list || []), ...names],
      selected_file_list: names
    }))
  },
  counts: (value) => {
    useAppStore.setState({ network_preview_data: value })
  },
  overview: (value) => {
    useAppStore.setState({ overview_data: value })
  },
  krona: (value) => {
    useAppStore.setState({ krona_data: value })
  },
  chord: (value) => {
    useAppStore.setState({ chord_data: value })
  },
  network: (value) => {
    useAppStore.setState({ network_data: value })
  },
  graph: (value) => {
    useAppStore.setState({ graph_data: value })
  },
  pathway_list: (value) => {
    useAppStore.setState({ pathway_list: value as string[] })
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
    text = selected_file_list.join(' vs ')
  }
  return (
    <p>{text}</p>
  )
}

const ErrorBanner = (): React.JSX.Element | null => {
  const last_error = useAppStore((state) => state.last_error)
  if (!last_error) return null
  return (
    <div
      role="alert"
      style={{
        background: '#fde2e1',
        border: '1px solid #c0392b',
        color: '#642723',
        padding: '8px 12px',
        margin: '8px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        fontSize: '13px'
      }}
    >
      <span style={{ flex: 1 }}>{last_error}</span>
      <button onClick={() => useAppStore.setState({ last_error: null })}>Dismiss</button>
    </div>
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

  useEffect(() => {
    for (const [channel, handler] of Object.entries(channel_handlers) as [
      Channel,
      (v: unknown) => void
    ][]) {
      registerChannelHandler(channel, handler)
    }
    request('handshake', undefined, { silent: true })
  }, [])

  return (
    <>
      <NavBar />
      <ErrorBanner />
      <DataInfoBar />
      {isLoading && <LoadingLayer />}
      <div id="main-container">
        {mainState === 'upload' && <Upload />}
        {mainState === 'overview' && <Overview />}
        {mainState === 'krona' && <Krona />}
        {mainState === 'chord' && <Chord />}
        {mainState === 'network' && <Network />}
        {mainState === 'graph' && <Graph />}
      </div>
    </>
  )
}

export default App
