import { create } from 'zustand'
import type { ChordFilterValue } from '../chordFilters'
import type { CountsData } from '../pathwayListResponse'

// Define your store state interface
interface AppState {
  overview_data: any
  chord_data: any
  network_preview_data: any
  network_data: any
  pathway_list: string[]
  pathway_tax_breakdowns: Record<string, CountsData>
  krona_data: any
  isLoading: boolean
  file_list: string[]
  selected_file_list: string[]
  active_dataset_path: string | null
  selectedFile: File | null
  selected_ann_cat: ChordFilterValue
  graph_data: any
  selected_taxon: ChordFilterValue
  selected_pathway: string
  selected_annotations: string[]
  mainState: 'upload' | 'chord' | 'network' | 'graph' | 'overview' | 'krona'
  tax_rank: 'kingdom' | 'phylum' | 'family' | 'class' | 'order' | 'genus'
  ann_rank: 'pathway' | 'superpathway'
  // null = handshake not yet completed; true/false once known
  db_ready: boolean | null
  // most recent IPC error surfaced to the user; null when no error is pending
  last_error: string | null
}

export const useAppStore = create<AppState>(() => ({
  overview_data: {},
  chord_data: {},
  network_preview_data: {},
  network_data: {},
  pathway_list: [],
  pathway_tax_breakdowns: {},
  krona_data: {},
  isLoading: false,
  file_list: [],
  selectedFile: null,
  selected_file_list: [],
  active_dataset_path: null,
  selected_ann_cat: {},
  graph_data: {},
  selected_taxon: {},
  selected_pathway: '',
  selected_annotations: [],
  mainState: 'upload',
  tax_rank: 'phylum',
  ann_rank: 'superpathway',
  db_ready: null,
  last_error: null
}))
