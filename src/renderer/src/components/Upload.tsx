import { useEffect, useState } from 'react';
import { useAppStore } from '../store/AppStore'

function Upload(): React.JSX.Element {
        
    // internal file object preloading
    const [dataFile, setDataFile] = useState<File | null>();
    const [ecFile, setEcFile] = useState<File | null>();
    const [dataFileLoad, setDataFileLoad] = useState(false);
    const [ecFileLoad, setEcFileLoad] = useState(false);
    // global state with actual data object
    const data = useAppStore((state) => (state.data))
    const ec = useAppStore((state) => (state.ec))
    // const isLoading = useAppStore((state) => (state.isLoading))
    
    // React hook to set mainState to 'chord' when both data and ec are non-null
    useEffect(() => {
        if (data && ec && !dataFileLoad && !ecFileLoad) {
            useAppStore.setState({ mainState: 'chord', isLoading: false })
        }
    }, [dataFileLoad, ecFileLoad])

    const handleDataFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) { setDataFile(file); setDataFileLoad(true) }
    }
    const handleECFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) { setEcFile(file); setEcFileLoad(true) }
    }
    
    //create the handleFileChange function that will be called when the file input changes
    // when the ipcRenderer replies with the parsed csv data, set the data in the app store and set the main state to chord
    const handleUploadClick = (_event: React.MouseEvent<HTMLButtonElement>) => {
        if (dataFile && ecFile) {
            // Read the file content using FileReader API
            const dataReader = new FileReader();
            dataReader.onload = (e) => {
                const fileContent = e.target?.result as string;
                if (fileContent) {
                    window.electron.ipcRenderer.send('parse-data', fileContent);
                }
            };
            // Listen for the parsed CSV response
            window.electron.ipcRenderer.on('parsed-data', (_event, data) => {
                console.log(data);
                useAppStore.setState({ data: data });
                setEcFileLoad(false)
            });
            dataReader.readAsText(dataFile);

            // do the same for ECs
            const ecReader = new FileReader();
            ecReader.onload = (e) => {
                const fileContent = e.target?.result as string;
                if (fileContent) {
                    window.electron.ipcRenderer.send('parse-ec', fileContent);
                }
            };
            ecReader.readAsText(ecFile);
            window.electron.ipcRenderer.on('parsed-ec', (_event, ec) => {
                console.log(ec);
                useAppStore.setState({ ec: ec });
                setDataFileLoad(false)
            });
        }
    };

    return (
        <div>
            <p>RPKM File</p>
            <input type="file" id="dataFile" accept="text/csv" onChange={handleDataFileChange} />
            <p>EC File</p>
            <input type="file" id="ecFile" accept="text/csv" onChange={handleECFileChange} />
            <button onClick={handleUploadClick}>Load Files</button>
        </div>
    )
}

export default Upload;