import { app, shell, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'

import {
  parse_ec_chord,
  initialize,
  add_data,
  parse_krona,
  parse_network,
  parse_pathway_list,
  parse_counts,
  parse_overview,
  add_test_data
} from './data_functions'

const api = [
  {
    channel: 'handshake',
    handler: initialize
  },
  {
    channel: 'load',
    handler: add_data
  },
  {
    channel: 'load_test',
    handler: add_test_data
  },
  {
    channel: 'overview',
    handler: parse_overview
  },
  {
    channel: 'counts',
    handler: parse_counts
  },
  {
    channel: 'krona',
    handler: parse_krona
  },
  {
    channel: 'chord',
    handler: parse_ec_chord
  },
  {
    channel: 'network',
    handler: parse_network
  },
  {
    channel: 'pathway_list',
    handler: parse_pathway_list
  }
]

function createWindow(): void {
  // Create the browser window.
  const mainWindow = new BrowserWindow({
    width: 1000,
    height: 850,
    show: false,
    autoHideMenuBar: true,
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // HMR for renderer base on electron-vite cli.
  // Load the remote URL for development or the local html file for production.
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(() => {
  // Set app user model id for windows
  electronApp.setAppUserModelId('com.electron')

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production.
  // see https://github.com/alex8088/electron-toolkit/tree/master/packages/utils
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  createWindow()

  // Wire the API. Every handler is wrapped so that a thrown error always
  // produces a reply; without this, an exception silently leaves the renderer
  // hanging on `isLoading: true` forever.
  // Wire format: { ok: true, value } | { ok: false, error }
  for (const { channel, handler } of api) {
    ipcMain.on(`request-${channel}`, (event, params) => {
      try {
        const value = handler(params)
        event.reply(`response-${channel}`, { ok: true, value })
      } catch (err) {
        const error = err instanceof Error ? err.message : String(err)
        console.error(`[ipc:${channel}] handler threw:`, err)
        event.reply(`response-${channel}`, { ok: false, error })
      }
    })
  }

  app.on('activate', function () {
    // On macOS it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// In this file you can include the rest of your app's specific main process
// code. You can also put them in separate files and require them here.
