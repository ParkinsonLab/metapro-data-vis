import { useEffect, useState } from 'react'
import { useAppStore } from '../store/AppStore'
import { parse_data, get_krona_data } from '../../../main/parse'

const DataSelector = () => {
  const file_list = useAppStore((state) => state.file_list)
  const [f1, set_f1] = useState('')
  const [f2, set_f2] = useState('')

  const default_settings = {
    selected_ann_cat: {},
    selected_taxon: {},
    selected_pathway: '',
    selected_annotations: [],
    tax_rank: 'phylum',
    ann_rank: 'superpathway'
  }

  const handleDropdown_1 = (e) => {
    set_f1(e.target.value)
  }
  const handleDropdown_2 = (e) => {
    set_f2(e.target.value)
  }
  const handleUpdate = () => {
    useAppStore.setState({ selected_file_list: [f1, f2].filter((e) => e) })
    window.electron.ipcRenderer.send('request-chord', {
      names: [f1, f2],
      tax_level: default_settings.tax_rank,
      ann_level: default_settings.ann_rank,
      selected_ann_cat: default_settings.selected_ann_cat,
      selected_taxon: default_settings.selected_taxon,
    })
  }

  return (
    <div>
      <select value={f1} onChange={handleDropdown_1}>
        <option value="">Select File 1</option>
        {file_list.map((file, idx) => (
          <option key={idx} value={file}>
            {file}
          </option>
        ))}
      </select>
      <select value={f2} onChange={handleDropdown_2}>
        <option value="">Select File 2</option>
        {file_list.map((file, idx) => (
          <option key={idx} value={file}>
            {file}
          </option>
        ))}
      </select>
      <button onClick={handleUpdate}>Update</button>
    </div>
  )
}

const Upload = (): React.JSX.Element => {
  // // internal file object preloading
  const [data_file, set_data_file] = useState<File | null>()
  const [data_name, set_data_name] = useState('')

  // const [ec_file, set_ec_file] = useState<File | null>()
  // const [data_file_load, set_data_file_load] = useState(false)
  // const [ec_file_load, set_ec_file_load] = useState(false)
  // // global state with actual data object
  // const data = useAppStore((state) => state.data)
  // const ec = useAppStore((state) => state.ec)
  // const tax_rank = useAppStore((state) => state.tax_rank)
  // const ann_rank = useAppStore((state) => state.ann_rank)
  // const isLoading = useAppStore((state) => state.isLoading)

  // // React hook to set mainState to 'chord' when both data and ec are non-null
  // useEffect(() => {
  //   if (data && ec && !data_file_load && !ec_file_load && isLoading) {
  //     parse_data(data, ec, tax_rank, ann_rank)
  //     get_krona_data(data, tax_rank)
  //     useAppStore.setState({ mainState: 'overview' })
  //   }
  // }, [data_file_load, ec_file_load])

  const handleDataFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      set_data_file(file)
      // set_data_file_load(true)
    }
  }
  // const handleECFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
  //   const file = event.target.files?.[0]
  //   if (file) {
  //     set_ec_file(file)
  //     set_ec_file_load(true)
  //   }
  // }

  //create the handleFileChange function that will be called when the file input changes
  // when the ipcRenderer replies with the parsed csv data, set the data in the app store and set the main state to chord
  const handleUploadClick = (_event: React.MouseEvent<HTMLButtonElement>) => {
    if (data_file) {
      // Read the file content using FileReader API
      const dataReader = new FileReader()
      dataReader.onload = (e) => {
        const fileContent = e.target?.result as string
        if (fileContent) {
          window.electron.ipcRenderer.send('request-load', {
            name: data_name,
            data: fileContent,
            test: false
          })
        }
      }
      dataReader.readAsText(data_file)
    }
  }

  const handleTestFileClick = () => {
    // contents mostly copied from the real thing
    window.electron.ipcRenderer.send('request-load_test')
  }

  return (
    <div>
      <p>Data Label</p>
      <input
        type="text"
        placeholder="Enter data label"
        value={data_name}
        onChange={(e) => set_data_name(e.target.value)}
      />
      <p>RPKM File</p>
      <input type="file" id="dataFile" accept="text/csv" onChange={handleDataFileChange} />
      <div>
        <button onClick={handleUploadClick}>Load Files</button>
        <button onClick={handleTestFileClick}>Load Test Files</button>
      </div>
      <DataSelector />
    </div>
  )
}

export default Upload
