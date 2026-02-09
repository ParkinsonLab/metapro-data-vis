import { app, shell, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'

import { parse_ec_chord, initialize, add_data } from './data_functions'

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
    channel: 'chord',
    handler: parse_ec_chord
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

  // set the API
  api.forEach((e) => {
    ipcMain.on(`request-${e.channel}`, (event, params) => {
      event.reply(`response-${e.channel}`, e.handler(params))
    })
  })

  // // Add the parse-csv event listener
  // //  when ipcMain receives the 'parse-csv' event with file content, use parse function from csv-parse/sync to parse the csv content into a json object and send the json object back to the renderer process
  // ipcMain.on('parse-data', (event, fileContent) => {
  //   const json = parse(fileContent, {
  //     columns: true,
  //     skip_empty_lines: true
  //   })
  //   event.reply('parsed-data', json)
  // })

  // // add another one for test data
  // ipcMain.on('parse-test', (event) => {
  //   event.reply('parsed-data', test_data)
  //   event.reply('parsed-ec', ec_data)
  // })

  // // place nodes
  // ipcMain.on('request-node-info', (event, pathway: number) => {
  //   console.log('backend request node info')
  //   event.reply('return-node-info', get_pathway_info(pathway))
  // })

  // // get taxonomic categories
  // // if a filter is supplied, filter the results before returning
  // // it's a bit awkward converting back to an obj, but this avoid a separate db function
  // ipcMain.on('get-tax-cats', (event, names: string[], level: string, filter: any = {}) => {
  //   let result
  //   if (_.isEmpty(filter)) {
  //     result = get_parents_at_level(names, level)
  //   } else {
  //     const raw_result = get_parents_multilevel(names, [filter.level, level])
  //     result = Object.fromEntries(
  //       raw_result
  //         .filter((e) => e[filter.level] === filter.name && e[level])
  //         .map((e) => [e.id, e[level]])
  //     )
  //   }
  //   event.reply('got-tax-cats', result)
  // })

  // // get taxonomic data for krona
  // ipcMain.on('get-tax-tree', (event, names: string[], levels: string[], filter: any = {}) => {
  //   let result
  //   let raw_result
  //   if (_.isEmpty(filter)) {
  //     result = get_parents_multilevel(names, levels)
  //   } else {
  //     if (!levels.includes(filter.level)) {
  //       raw_result = get_parents_multilevel(names, [...levels, filter.level])
  //     } else {
  //       raw_result = get_parents_multilevel(names, levels)
  //     }
  //     result = raw_result
  //       .filter((e) => e[filter.level] === filter.name)
  //       .map((e) => _.pick(e, ['id', ...levels]))
  //   }
  //   event.reply('got-tax-tree', result)
  // })

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
