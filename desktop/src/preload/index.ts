import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('flaxie', {
  // Chat panel
  toggleChat: () => ipcRenderer.send('toggle-chat'),
  closeChat:  () => ipcRenderer.send('close-chat'),

  // Notification banner
  closeNotif:  () => ipcRenderer.send('close-notif'),
  openChat:    () => ipcRenderer.send('open-chat-from-notif'),
  dismissNudge: () => ipcRenderer.send('dismiss-nudge'),

  // Mascot (legacy / kept for compat)
  dragMascot: (delta: { x: number; y: number }) => ipcRenderer.send('mascot-drag', delta),

  // Backend URL
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),

  // Tell main process the real user ID so WebSocket uses correct user
  setUserId: (userId: string) => ipcRenderer.send('set-user-id', userId),

  // Notification data (renderer calls this on mount as fallback)
  getNotifData: () => ipcRenderer.invoke('get-notif-data'),
  resizeNotif: (height: number) => ipcRenderer.send('resize-notif', height),

  // Event listeners — chat window
  onMascotState: (cb: (msg: object) => void) => {
    const handler = (_: unknown, msg: object) => cb(msg)
    ipcRenderer.on('mascot-state', handler)
    return () => ipcRenderer.removeListener('mascot-state', handler)
  },
  onNudge: (cb: (nudge: object) => void) => {
    const handler = (_: unknown, nudge: object) => cb(nudge)
    ipcRenderer.on('nudge', handler)
    return () => ipcRenderer.removeListener('nudge', handler)
  },
  onReflection: (cb: (data: object) => void) => {
    const handler = (_: unknown, data: object) => cb(data)
    ipcRenderer.on('reflection', handler)
    return () => ipcRenderer.removeListener('reflection', handler)
  },
  onChatOpened: (cb: () => void) => {
    ipcRenderer.on('chat-opened', cb)
    return () => ipcRenderer.removeListener('chat-opened', cb)
  },
  onChatClosed: (cb: () => void) => {
    ipcRenderer.on('chat-closed', cb)
    return () => ipcRenderer.removeListener('chat-closed', cb)
  },
  onNudgeDismissed: (cb: () => void) => {
    ipcRenderer.on('nudge-dismissed', cb)
    return () => ipcRenderer.removeListener('nudge-dismissed', cb)
  },
  onFlash: (cb: () => void) => {
    ipcRenderer.on('flash', cb)
    return () => ipcRenderer.removeListener('flash', cb)
  },

  // Event listeners — notif banner window
  onNotifData: (cb: (data: object) => void) => {
    const handler = (_: unknown, data: object) => cb(data)
    ipcRenderer.on('notif-data', handler)
    return () => ipcRenderer.removeListener('notif-data', handler)
  },
})

export type MascotState =
  | 'idle' | 'alert' | 'listening' | 'celebrating' | 'concerned' | 'dormant' | 'urgent'

export interface NudgePayload {
  id: string
  message: string
  task_id?: string
  task_title?: string
  action_options: string[]
}
