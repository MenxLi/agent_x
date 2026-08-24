import { defineStore } from 'pinia'

const KEY = 'xun.input-history'
const LIMIT = 50

function load(): string[] {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(stored) ? stored.filter((entry): entry is string => typeof entry === 'string') : []
  } catch {
    return []
  }
}

export const useInputHistoryStore = defineStore('inputHistory', {
  state: () => ({ entries: load() }),
  actions: {
    add(text: string) {
      this.entries = [text, ...this.entries.filter(entry => entry !== text)].slice(0, LIMIT)
      try {
        localStorage.setItem(KEY, JSON.stringify(this.entries))
      } catch {
        // storage unavailable — history stays in-memory only
      }
    },
  },
})
