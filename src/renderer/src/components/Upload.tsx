import { useAppStore } from '../store/AppStore'

function Upload(): React.JSX.Element {
        
    //create the handleFileChange function that will be called when the file input changes
    // when the ipcRenderer replies with the parsed csv data, set the data in the app store and set the main state to chord
    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) {
            // Read the file content using FileReader API
            const reader = new FileReader();
            reader.onload = (e) => {
                const fileContent = e.target?.result as string;
                if (fileContent) {
                    window.electron.ipcRenderer.send('parse-csv', fileContent);
                }
            };
            reader.readAsText(file);
            
            // Listen for the parsed CSV response
            window.electron.ipcRenderer.on('parsed-csv', (_event, data) => {
                console.log(data);
                useAppStore.setState({ data: data });
                useAppStore.setState({ mainState: 'chord' });
            });
        }
    };

    return <input type="file" accept="text/csv" onChange={handleFileChange} />;
}

export default Upload;