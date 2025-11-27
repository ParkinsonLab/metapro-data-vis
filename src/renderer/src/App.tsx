import Upload from './components/Upload'
import Chord from './components/Chord'
import Network from './components/Network'
import Plot from './components/Plot'
import { useAppStore } from './store/AppStore'
import { useEffect, useState } from 'react'
import './App.css'

const NavBar = () => {

    const state_map = {
        'nav-upload': 'upload',
        'nav-chord': 'chord',
        'nav-network': 'network',
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
                <div id='nav-chord' onClick={handleNavClick} className={mainState === state_map["nav-chord"] ? "bold" : ""}>
                    Chord
                </div>
                <div id='nav-network' onClick={handleNavClick} className={mainState === state_map["nav-network"] ? "bold" : ""}>
                    Network
                </div>
            </div>
        </>
    )
}

const App = (): React.JSX.Element => {

    // use the useStore hook to check the overall state of the app called appState. Depending on whether the state is
    // upload, chord, network, or plot, show the corresponding component.
    const mainState = useAppStore((state) => state.mainState)
    console.log(mainState + ' from app')
    return (
        <>
            <NavBar />
            <div id="main-container">
                {mainState === 'upload' && <Upload />}
                {mainState === 'chord' && <Chord />}
                {mainState === 'network' && <Network />}
                {mainState === 'plot' && <Plot />}
            </div>
        </>
    )
}

export default App
