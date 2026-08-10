<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Files, PanelLeftClose, Send, Wifi, WifiOff } from 'lucide-vue-next'
import { api } from './api'
import EventStream from './components/EventStream.vue'
import FileBrowser from './components/FileBrowser.vue'
import PromptDialog from './components/PromptDialog.vue'
import type { AgentInfo, CommandInfo, DisplayEvent, PendingPrompt } from './types'

const events = ref<DisplayEvent[]>([])
const agents = ref<AgentInfo[]>([])
const commands = ref<CommandInfo[]>([])
const input = ref('')
const connected = ref(false)
const markdown = ref(localStorage.getItem('xun-markdown') !== 'false')
const filesOpen = ref(window.innerWidth >= 900)
const selectedCommand = ref(0)
const pendingPrompt = ref<PendingPrompt | null>(null)
const streamElement = ref<HTMLElement>()
const textarea = ref<HTMLTextAreaElement>()
let socket: WebSocket | null = null
let reconnectTimer: number | undefined

const commandQuery = computed(() => {
  if (!input.value.startsWith('/') || input.value.includes('\n')) return null
  return input.value.slice(1).split(/\s/, 1)[0].toLowerCase()
})
const filteredCommands = computed(() => commandQuery.value === null ? [] : commands.value.filter(command =>
  command.name.toLowerCase().includes(commandQuery.value!) || command.description.toLowerCase().includes(commandQuery.value!),
))

watch(markdown, value => localStorage.setItem('xun-markdown', String(value)))
watch(events, () => nextTick(() => {
  if (streamElement.value) streamElement.value.scrollTop = streamElement.value.scrollHeight
}), { deep: true })
watch(filteredCommands, () => { selectedCommand.value = 0 })

async function loadInitialData() {
  const [eventData, agentData, commandData] = await Promise.all([api.events(), api.agents(), api.commands()])
  events.value = eventData
  agents.value = agentData
  commands.value = commandData
}

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${protocol}://${location.host}/ws`)
  socket.addEventListener('open', async () => {
    connected.value = true
    await loadInitialData().catch(() => undefined)
  })
  socket.addEventListener('message', message => {
    const payload = JSON.parse(message.data) as DisplayEvent | { type: 'pending_prompt'; data: PendingPrompt }
    if ('type' in payload && payload.type === 'pending_prompt') pendingPrompt.value = payload.data
    else events.value.push(payload as DisplayEvent)
  })
  socket.addEventListener('close', () => {
    connected.value = false
    reconnectTimer = window.setTimeout(connect, 2500)
  })
}

function send(payload: Record<string, unknown>) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload))
}

function submit() {
  const value = input.value.trim()
  if (!value || !connected.value) return
  if (value.startsWith('/')) {
    const [name, ...argumentsParts] = value.slice(1).split(/\s+/)
    send({ type: 'command', name, arguments: argumentsParts.join(' ') || null })
  } else {
    send({ type: 'message', content: value })
  }
  input.value = ''
  resizeInput()
}

function chooseCommand(command: CommandInfo) {
  input.value = `/${command.name} `
  selectedCommand.value = 0
  nextTick(() => textarea.value?.focus())
}

function handleKeydown(event: KeyboardEvent) {
  if (filteredCommands.value.length) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      selectedCommand.value = (selectedCommand.value + 1) % filteredCommands.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      selectedCommand.value = (selectedCommand.value - 1 + filteredCommands.value.length) % filteredCommands.value.length
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      chooseCommand(filteredCommands.value[selectedCommand.value])
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

function resizeInput() {
  nextTick(() => {
    if (!textarea.value) return
    textarea.value.style.height = 'auto'
    textarea.value.style.height = `${Math.min(textarea.value.scrollHeight, 180)}px`
  })
}

function answerPrompt(value: string) {
  send({ type: 'choice', value })
  pendingPrompt.value = null
}

onMounted(connect)
onBeforeUnmount(() => {
  window.clearTimeout(reconnectTimer)
  socket?.close()
})
</script>

<template>
  <div class="app-shell" :class="{ 'files-visible': filesOpen }">
    <div v-if="filesOpen" class="mobile-scrim" @click="filesOpen = false" />
    <FileBrowser v-if="filesOpen" :agents="agents" @close="filesOpen = false" />

    <main class="chat-shell">
      <header class="topbar">
        <div class="brand">
          <button class="icon-button file-toggle" :title="filesOpen ? 'Hide files' : 'Show files'" @click="filesOpen = !filesOpen">
            <PanelLeftClose v-if="filesOpen" :size="18" />
            <Files v-else :size="18" />
          </button>
          <div><h1>Xun</h1><span>Agent workspace</span></div>
        </div>
        <div class="topbar-actions">
          <label class="markdown-toggle" title="Render messages as Markdown"><input v-model="markdown" type="checkbox"> MD</label>
          <span class="connection" :class="{ connected }"><Wifi v-if="connected" :size="14" /><WifiOff v-else :size="14" />{{ connected ? 'Connected' : 'Reconnecting' }}</span>
        </div>
      </header>

      <section ref="streamElement" class="conversation" aria-live="polite">
        <div v-if="!events.length" class="empty-chat"><strong>What are we working on?</strong><span>Send a message or type / for commands.</span></div>
        <EventStream v-else :events="events" :markdown="markdown" />
      </section>

      <footer class="composer-area">
        <div class="composer-wrap">
          <div v-if="filteredCommands.length" class="command-menu">
            <button v-for="(command, index) in filteredCommands" :key="command.name" :class="{ selected: index === selectedCommand }" @mousedown.prevent="chooseCommand(command)">
              <code>/{{ command.name }}</code><span>{{ command.description }}</span>
            </button>
          </div>
          <div class="composer">
            <textarea ref="textarea" v-model="input" rows="1" placeholder="Message Xun or type / for commands" :disabled="!connected" @input="resizeInput" @keydown="handleKeydown" />
            <button class="send-button" title="Send" :disabled="!connected || !input.trim()" @click="submit"><Send :size="18" /></button>
          </div>
          <span class="composer-hint">Enter to send · Shift+Enter for a new line</span>
        </div>
      </footer>
    </main>

    <PromptDialog v-if="pendingPrompt" :prompt="pendingPrompt" @submit="answerPrompt" />
  </div>
</template>
