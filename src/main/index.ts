import { app, shell, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import _ from 'lodash';
import { parse } from "csv-parse/sync";
import place_nodes from './place_nodes';
import get_parents_at_level from './get_taxonomy';
import fs from 'fs';
import path from 'path';

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

// preload test data
const test_data = parse(
    fs.readFileSync(path.join(__dirname, '../../resources/example_data/new_ec_rpkm.tsv'), 'utf8'),
    { columns: true, skip_empty_lines: true, delimiter: "\t" }
)
const test_ec = parse(
    fs.readFileSync(path.join(__dirname, '../../resources/example_data/ec_coverage.csv'), 'utf8'),
    { columns: true, skip_empty_lines: true }
).slice(0, -3)

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

    // IPC test
    ipcMain.on('ping', () => console.log('pong'))

    createWindow()

    // Add the parse-csv event listener
    //  when ipcMain receives the 'parse-csv' event with file content, use parse function from csv-parse/sync to parse the csv content into a json object and send the json object back to the renderer process
    ipcMain.on('parse-data', (event, fileContent) => {
        const json = parse(fileContent, {
            columns: true,
            skip_empty_lines: true
        })
        event.reply('parsed-data', json)
    })

    // similar listener for a second ec file
    // the two are separated to accomodate for possible differences
    // but so far are the same
    ipcMain.on('parse-ec', (event, fileContent) => {
        const json = parse(fileContent, {
            columns: true,
            skip_empty_lines: true,
        })
        event.reply('parsed-ec', json.slice(0, -3))
    })

    // add another one for test data
    ipcMain.on('parse-test', (event) => {
        event.reply('parsed-data', test_data)
        event.reply('parsed-ec', test_ec)
    })

    // place nodes
    ipcMain.on('place-nodes', (event, pathway: string, nodes: string[]) => {
        try {
            event.reply('placed-nodes', place_nodes(pathway, nodes))
        } catch (e) {
            console.log(e)
            event.reply('placed-nodes', null) // if node placement crashes, just don't do anything
        }
    })

    // get taxonomic categories
    ipcMain.on('get-tax-cats', (event, names: string[], level: string) => {
        event.reply('got-tax-cats', get_parents_at_level(names, level))
    })

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

