/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DATA_MODE?: 'mounted' | 'upload'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
