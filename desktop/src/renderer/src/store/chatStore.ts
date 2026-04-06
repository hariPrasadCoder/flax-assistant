import { create } from 'zustand'
import type { Message } from '../chat/MessageBubble'
import type { Task } from '../chat/TaskChip'

interface ChatStore {
  messages: Message[]
  tasks: Task[]
  isLoading: boolean
  backendUrl: string
  userId: string | null
  teamId: string | null

  setBackendUrl: (url: string) => void
  setAuth: (userId: string, teamId: string | null) => void
  addMessage: (msg: Message) => void
  setTasks: (tasks: Task[]) => void
  updateTaskStatus: (taskId: string, status: Task['status']) => void
  setLoading: (v: boolean) => void
  clearMessages: () => void
}

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],
  tasks: [],
  isLoading: false,
  backendUrl: 'http://localhost:8747',
  userId: null,
  teamId: null,

  setBackendUrl: (url) => set({ backendUrl: url }),
  setAuth: (userId, teamId) => set({ userId, teamId }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  setTasks: (tasks) => set({ tasks }),
  updateTaskStatus: (taskId, status) =>
    set((s) => ({
      tasks: s.tasks.map((t) => (t.id === taskId ? { ...t, status } : t)),
    })),
  setLoading: (isLoading) => set({ isLoading }),
  clearMessages: () => set({ messages: [] }),
}))
