import {
  app,
  BrowserWindow,
  ipcMain,
  screen,
  globalShortcut,
  Menu,
  Tray,
  nativeImage,
} from 'electron'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) { app.quit(); process.exit(0) }

let chatWindow: BrowserWindow | null = null
let notifWindow: BrowserWindow | null = null
let tray: Tray | null = null
let wsReconnectTimer: NodeJS.Timeout | null = null
let wsInstance: any = null
let wsAlive = true
let pendingNotifData: object | null = null
let activeUserId = 'local'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8747'
const WS_BASE_URL = process.env.WS_URL      || 'ws://localhost:8747/ws/mascot'
const CHAT_WIDTH  = 380
const CHAT_HEIGHT = 540
const NOTIF_WIDTH  = 380
const NOTIF_HEIGHT = 160
const IS_MAC      = process.platform === 'darwin'

// ── Tray icon (PNG files) ─────────────────────────────────────────────────────

function getTrayIconPath(state: 'idle' | 'alert' | 'urgent' = 'idle'): string {
  const base = state === 'urgent' ? 'trayIconUrgent' : state === 'alert' ? 'trayIconAlert' : 'trayIcon'
  return join(__dirname, `../../resources/${base}.png`)
}

function makeTrayIcon(state: 'idle' | 'alert' | 'urgent' = 'idle'): Electron.NativeImage {
  const img = nativeImage.createFromPath(getTrayIconPath(state))
  if (IS_MAC && state === 'idle') img.setTemplateImage(true)
  return img
}

// ── Chat panel ────────────────────────────────────────────────────────────────

function getChatPosition(): { x: number; y: number } {
  const trayBounds = tray?.getBounds()
  const { width: sw, height: sh } = screen.getPrimaryDisplay().workAreaSize

  if (trayBounds) {
    const x = Math.min(
      Math.max(trayBounds.x - CHAT_WIDTH / 2 + trayBounds.width / 2, 8),
      sw - CHAT_WIDTH - 8
    )
    const y = IS_MAC ? trayBounds.y + trayBounds.height + 4 : sh - CHAT_HEIGHT - 48
    return { x, y }
  }
  return { x: sw - CHAT_WIDTH - 16, y: sh - CHAT_HEIGHT - 48 }
}

function createChatWindow(): BrowserWindow {
  const { x, y } = getChatPosition()

  const win = new BrowserWindow({
    width: CHAT_WIDTH,
    height: CHAT_HEIGHT,
    x, y,
    frame: false,
    transparent: false,
    hasShadow: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    acceptFirstMouse: true,
    backgroundColor: '#F8F7FE',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
    },
  })

  win.setAlwaysOnTop(true, 'floating')
  if (IS_MAC) win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: false })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/chat.html`)
  } else {
    win.loadFile(join(__dirname, '../renderer/chat.html'))
  }

  win.once('ready-to-show', () => win.show())

  win.on('blur', () => {
    setTimeout(() => {
      if (chatWindow && !chatWindow.isDestroyed() && chatWindow.isVisible()) {
        chatWindow.hide()
      }
    }, 150)
  })

  return win
}

function toggleChat() {
  if (!chatWindow || chatWindow.isDestroyed()) {
    chatWindow = createChatWindow()
    return
  }
  if (chatWindow.isVisible()) {
    chatWindow.hide()
  } else {
    const { x, y } = getChatPosition()
    chatWindow.setBounds({ x, y, width: CHAT_WIDTH, height: CHAT_HEIGHT })
    chatWindow.show()
    chatWindow.focus()
  }
}

// ── Custom notification banner ────────────────────────────────────────────────

function getNotifPosition(): { x: number; y: number } {
  const { width: sw } = screen.getPrimaryDisplay().bounds  // use full bounds, not workArea
  const menuBarHeight = IS_MAC ? 28 : 0
  return {
    x: sw - NOTIF_WIDTH - 16,
    y: menuBarHeight + 12,
  }
}

function showCustomNotif(nudgeId: string, message: string, taskTitle?: string, actions?: string[], taskId?: string) {
  // Close existing notif if any
  if (notifWindow && !notifWindow.isDestroyed()) {
    notifWindow.destroy()
    notifWindow = null
  }

  const notifData = {
    nudgeId,
    message,
    taskTitle,
    taskId,
    actions: actions || ['Got it', "Let's talk"],
    backendUrl: BACKEND_URL,
  }

  const { x, y } = getNotifPosition()

  notifWindow = new BrowserWindow({
    width: NOTIF_WIDTH,
    height: NOTIF_HEIGHT,
    x, y,
    frame: false,
    transparent: true,
    hasShadow: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    acceptFirstMouse: true,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
    },
  })

  // 'screen-saver' level sits above everything including full-screen apps
  pendingNotifData = notifData

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    notifWindow.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/notif.html`)
  } else {
    notifWindow.loadFile(join(__dirname, '../renderer/notif.html'))
  }

  notifWindow.once('ready-to-show', () => {
    // Set window level AFTER show so macOS actually applies it across Spaces
    notifWindow?.setAlwaysOnTop(true, 'screen-saver')
    if (IS_MAC) notifWindow?.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    notifWindow?.show()
    // Small delay so renderer is ready before we push data + trigger slide-in
    setTimeout(() => {
      notifWindow?.webContents.send('notif-data', notifData)
    }, 80)
  })

  notifWindow.on('closed', () => { notifWindow = null })

  // Update tray icon
  tray?.setImage(makeTrayIcon('alert'))
}

function closeNotifWindow() {
  if (notifWindow && !notifWindow.isDestroyed()) {
    notifWindow.destroy()
    notifWindow = null
  }
  tray?.setImage(makeTrayIcon('idle'))
}

// ── WebSocket relay ───────────────────────────────────────────────────────────

function stopWSRelay() {
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null }
  if (wsInstance) {
    try { wsInstance.terminate() } catch { /* ignore */ }
    wsInstance = null
  }
}

function startWSRelay() {
  if (!wsAlive) return
  stopWSRelay()
  try {
    const { WebSocket: WS } = require('ws') as { WebSocket: new (url: string) => any }
    const wsUrl = `${WS_BASE_URL}?user_id=${encodeURIComponent(activeUserId)}`
    const ws = new WS(wsUrl)
    wsInstance = ws
    ws.on('open', () => console.log(`[ws] connected as ${activeUserId}`))
    ws.on('message', (data: Buffer) => {
      try {
        const msg = JSON.parse(data.toString()) as {
          type: string; state?: string; id?: string
          message?: string; task_title?: string; action_options?: string[]; task_id?: string
        }
        if (msg.type === 'nudge') {
          showCustomNotif(msg.id || '', msg.message || '', msg.task_title, msg.action_options, msg.task_id)
        } else if (msg.type === 'mascot_state') {
          const state = msg.state as string
          if (state === 'urgent') tray?.setImage(makeTrayIcon('urgent'))
          else if (state === 'alert') tray?.setImage(makeTrayIcon('alert'))
          else tray?.setImage(makeTrayIcon('idle'))
        }
        chatWindow?.webContents.send('mascot-state', msg)
        if (msg.type === 'nudge') chatWindow?.webContents.send('nudge', msg)
      } catch { /* ignore */ }
    })
    ws.on('close', () => { if (wsAlive) wsReconnectTimer = setTimeout(startWSRelay, 3000) })
    ws.on('error', () => {})
  } catch {
    wsReconnectTimer = setTimeout(startWSRelay, 5000)
  }
}

// ── IPC ───────────────────────────────────────────────────────────────────────

function registerIPC() {
  ipcMain.on('toggle-chat', toggleChat)
  ipcMain.on('close-chat', () => chatWindow?.hide())
  ipcMain.on('close-notif', closeNotifWindow)
  ipcMain.on('resize-notif', (_event, height: number) => {
    if (notifWindow && !notifWindow.isDestroyed()) {
      notifWindow.setSize(NOTIF_WIDTH, Math.min(height + 20, 500))
    }
  })
  ipcMain.on('open-chat-from-notif', () => { closeNotifWindow(); toggleChat() })
  ipcMain.on('dismiss-nudge', () => tray?.setImage(makeTrayIcon('idle')))
  ipcMain.handle('get-backend-url', () => BACKEND_URL)
  ipcMain.handle('get-notif-data', () => pendingNotifData)

  // Renderer sends real user ID after login — reconnect WS under correct user
  ipcMain.on('set-user-id', (_event, userId: string) => {
    if (!userId || userId === activeUserId) return
    console.log(`[ws] switching user: ${activeUserId} → ${userId}`)
    activeUserId = userId
    startWSRelay()  // reconnect immediately with new user_id
  })
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  if (IS_MAC && app.dock) app.dock.hide()

  registerIPC()

  tray = new Tray(makeTrayIcon('idle'))
  tray.setToolTip('Flaxie — Click to chat')
  tray.on('click', toggleChat)
  tray.on('double-click', toggleChat)

  tray.on('right-click', () => {
    tray?.popUpContextMenu(Menu.buildFromTemplate([
      { label: 'Open Flaxie', click: toggleChat },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() },
    ]))
  })

  startWSRelay()

  globalShortcut.register('CommandOrControl+Shift+F', toggleChat)
})

app.on('window-all-closed', (e: Event) => e.preventDefault())

app.on('before-quit', () => {
  wsAlive = false
  stopWSRelay()
  globalShortcut.unregisterAll()
})

app.on('second-instance', toggleChat)
