import Upload from './components/Upload'
import Chord from './components/Chord'
import Network from './components/Network'
import Graph from './components/Graph'
import Overview from './components/Overview'
import { useAppStore } from './store/AppStore'
import { useEffect, useState } from 'react'
import { Oval } from 'react-loader-spinner'
import './App.css'

const NavBar = () => {

    const state_map = {
        'nav-upload': 'upload',
        'nav-chord': 'chord',
        'nav-network': 'network',
        'nav-graph': 'graph',
        'nav-overview': 'overview',
    }

    const mainState = useAppStore((state) => state.mainState)

    const handleNavClick = (event: React.MouseEvent<HTMLDivElement>) => {
        useAppStore.setState({ mainState: state_map[event.currentTarget.id] }) 
    }

    return (
        <>
            <p id='title'>Metapro Viz</p>
            <div id="nav-container">
                <div id='nav-upload' onClick={handleNavClick} className={mainState === state_map["nav-upload"] ? "bold" : ""}>
                    Upload
                </div>
                <div id='nav-overview' onClick={handleNavClick} className={mainState === state_map["nav-overview"] ? "bold" : ""}>
                    Overview
                </div>
                <div id='nav-chord' onClick={handleNavClick} className={mainState === state_map["nav-chord"] ? "bold" : ""}>
                    Chord
                </div>
                <div id='nav-network' onClick={handleNavClick} className={mainState === state_map["nav-network"] ? "bold" : ""}>
                    Network
                </div>
                <div id='nav-graph' onClick={handleNavClick} className={mainState === state_map["nav-graph"] ? "bold" : ""}>
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
    return <div id='loading-layer' onClick={handleClick}>
        <Oval
            visible={true}
            height="120"
            width="120"
            color="white"
            ariaLabel="oval-loading"
            wrapperClass=""
        />
    </div>
}

const App = (): React.JSX.Element => {

    // use the useStore hook to check the overall state of the app called appState. Depending on whether the state is
    // upload, chord, network, or plot, show the corresponding component.
    const mainState = useAppStore((state) => state.mainState)
    const isLoading = useAppStore(state => state.isLoading)
    console.log(mainState + ' from app')
    return (
        <>
            <NavBar />
            {isLoading && <LoadingLayer />}
            <div id="main-container">
                {mainState === 'upload' && <Upload />}
                {mainState === 'overview' && <Overview />}
                {mainState === 'chord' && <Chord />}
                {mainState === 'network' && <Network />}
                {mainState === 'graph' && <Graph />}
            </div>
        </>
    )
}

export default App
