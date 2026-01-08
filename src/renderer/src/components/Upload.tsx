import { useEffect, useState } from 'react'
import { useAppStore } from '../store/AppStore'
import parse_data from './parse';


const Upload = (): React.JSX.Element => {

    // internal file object preloading
    const [data_file, set_data_file] = useState<File | null>();
    const [ec_file, set_ec_file] = useState<File | null>();
    const [data_file_load, set_data_file_load] = useState(false);
    const [ec_file_load, set_ec_file_load] = useState(false);
    // global state with actual data object
    const data = useAppStore((state) => (state.data))
    const ec = useAppStore((state) => (state.ec))
    const tax_rank = useAppStore(state => state.tax_rank)
    const isLoading = useAppStore((state) => (state.isLoading))

    // React hook to set mainState to 'chord' when both data and ec are non-null
    useEffect(() => {
        if (data && ec && !data_file_load && !ec_file_load && isLoading) {
            parse_data(data, ec, tax_rank)
            useAppStore.setState({mainState: 'overview'})
        }
    }, [data_file_load, ec_file_load])

    const handleDataFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) { set_data_file(file); set_data_file_load(true) }
    }
    const handleECFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) { set_ec_file(file); set_ec_file_load(true) }
    }

    //create the handleFileChange function that will be called when the file input changes
    // when the ipcRenderer replies with the parsed csv data, set the data in the app store and set the main state to chord
    const handleUploadClick = (_event: React.MouseEvent<HTMLButtonElement>) => {
        if (data_file && ec_file) {
            // set state to isLoading
            useAppStore.setState({ isLoading: true })

            // Read the file content using FileReader API
            const dataReader = new FileReader();
            dataReader.onload = (e) => {
                const fileContent = e.target?.result as string;
                if (fileContent) {
                    window.electron.ipcRenderer.send('parse-data', fileContent);
                }
            };
            // Listen for the parsed CSV response
            window.electron.ipcRenderer.once('parsed-data', (_event, data) => {
                useAppStore.setState({ data: data });
                set_data_file_load(false)
            });
            dataReader.readAsText(data_file);

            // do the same for ECs
            const ecReader = new FileReader();
            ecReader.onload = (e) => {
                const fileContent = e.target?.result as string;
                if (fileContent) {
                    window.electron.ipcRenderer.send('parse-ec', fileContent);
                }
            };
            ecReader.readAsText(ec_file);
            window.electron.ipcRenderer.once('parsed-ec', (_event, ec) => {
                useAppStore.setState({ ec: ec });
                set_ec_file_load(false)
            });
        }
    };

    const handleTestFileClick = () => {
        // contents mostly copied from the real thing
        useAppStore.setState({ isLoading: true })
        set_ec_file_load(true)
        set_data_file_load(true)
        // Listen for the parsed CSV response
        window.electron.ipcRenderer.once('parsed-data', (_event, data) => {
            useAppStore.setState({ data: data });
            set_ec_file_load(false)
        });
        window.electron.ipcRenderer.once('parsed-ec', (_event, ec) => {
            useAppStore.setState({ ec: ec });
            set_data_file_load(false)
        });
        window.electron.ipcRenderer.send('parse-test');
    }

    return (
        <div>
            <p>RPKM File</p>
            <input type="file" id="dataFile" accept="text/csv" onChange={handleDataFileChange} />
            <p>EC File</p>
            <input type="file" id="ecFile" accept="text/csv" onChange={handleECFileChange} />
            <div>
                <button onClick={handleUploadClick}>Load Files</button>
                <button onClick={handleTestFileClick}>Load Test Files</button>
            </div>
        </div>
    )
}

export default Upload;