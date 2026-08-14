import { defineStore } from 'pinia'

export type Theme = 'system' | 'light' | 'dark'

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    theme: 'system' as Theme,
    markdown: true,
  }),
  persist: true,
})
