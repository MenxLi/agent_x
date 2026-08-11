<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Bot, Files, ImagePlus, PanelLeftClose, Send, Wifi, WifiOff, X } from 'lucide-vue-next'
import { api, appUrl } from './api'
import EventStream from './components/EventStream.vue'
import FileBrowser from './components/FileBrowser.vue'
import PromptDialog from './components/PromptDialog.vue'
import type { AgentInfo, ClientMessage, CommandInfo, DisplayEvent, ImageDescriptor, PendingPrompt, ServerMessage } from './types'

const events = ref<DisplayEvent[]>([])
const agents = ref<AgentInfo[]>([])
const selectedAgentId = ref('')
const selectedOnly = ref(false)
const commands = ref<CommandInfo[]>([])
const input = ref('')
const connected = ref(false)
const markdown = ref(localStorage.getItem('xun-markdown') !== 'false')
const filesOpen = ref(window.innerWidth >= 900)
const selectedCommand = ref(0)
const pendingPrompt = ref<PendingPrompt | null>(null)
const supportsVision = ref(false)
const images = ref<Array<{ file: File; url: string }>>([])
const sending = ref(false)
const sendError = ref('')
const streamElement = ref<HTMLElement>()
const textarea = ref<HTMLTextAreaElement>()
const imageInput = ref<HTMLInputElement>()
let socket: WebSocket | null = null
let reconnectTimer: number | undefined
let agentDataRequest = 0

const selectedAgent = computed(() => agents.value.find(agent => agent.identifier === selectedAgentId.value))
const visibleEvents = computed(() => selectedOnly.value && selectedAgentId.value
  ? events.value.filter(event => event.agent?.identifier === selectedAgentId.value)
  : events.value,
)

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
watch(selectedAgentId, async agentId => {
  const requestId = ++agentDataRequest
  commands.value = []
  supportsVision.value = false
  clearImages()
  if (!agentId) return
  try {
    const [commandData, capabilityData] = await Promise.all([api.commands(agentId), api.capabilities(agentId)])
    if (requestId !== agentDataRequest) return
    commands.value = commandData
    supportsVision.value = capabilityData.capabilities.includes('vision')
  } catch {
    if (requestId === agentDataRequest) commands.value = []
  }
})

async function loadInitialData() {
  const [eventData, agentData] = await Promise.all([api.events(), api.agents()])
  events.value = eventData
  agents.value = agentData
  ensureAgentSelection()
}

function ensureAgentSelection() {
  if (!agents.value.some(agent => agent.identifier === selectedAgentId.value)) {
    selectedAgentId.value = agents.value[0]?.identifier || ''
  }
}

function applyAgentEvent(event: DisplayEvent) {
  const agent = event.agent
  if (!agent) return
  if (event.name === 'AgentBindEvent') {
    const index = agents.value.findIndex(item => item.identifier === agent.identifier)
    if (index === -1) agents.value.push(agent)
    else agents.value[index] = agent
  } else if (event.name === 'AgentUnbindEvent') {
    agents.value = agents.value.filter(item => item.identifier !== agent.identifier)
  }
  ensureAgentSelection()
}

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${protocol}://${location.host}${appUrl('/ws')}`)
  socket.addEventListener('open', async () => {
    connected.value = true
    await loadInitialData().catch(() => undefined)
  })
  socket.addEventListener('message', message => {
    const payload = JSON.parse(message.data) as ServerMessage
    if (isPendingPrompt(payload)) pendingPrompt.value = payload.data
    else {
      applyAgentEvent(payload)
      events.value.push(payload)
    }
  })
  socket.addEventListener('close', () => {
    connected.value = false
    reconnectTimer = window.setTimeout(connect, 2500)
  })
}

function isPendingPrompt(payload: ServerMessage): payload is Extract<ServerMessage, { type: 'pending_prompt' }> {
  return 'type' in payload && payload.type === 'pending_prompt'
}

function send(payload: ClientMessage) {
  if (socket?.readyState !== WebSocket.OPEN) return false
  socket.send(JSON.stringify(payload))
  return true
}

function readImage(file: File): Promise<ImageDescriptor> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener('load', () => resolve({ kind: 'base64', value: String(reader.result) }))
    reader.addEventListener('error', () => reject(reader.error || new Error(`Could not read ${file.name}`)))
    reader.readAsDataURL(file)
  })
}

async function submit() {
  const value = input.value.trim()
  if ((!value && !images.value.length) || !connected.value || !selectedAgentId.value || sending.value) return
  sendError.value = ''
  if (value.startsWith('/')) {
    const [name, ...argumentsParts] = value.slice(1).split(/\s+/)
    send({ type: 'command', agent_id: selectedAgentId.value, name, arguments: argumentsParts.join(' ') || null })
  } else {
    sending.value = true
    try {
      const messageImages = await Promise.all(images.value.map(image => readImage(image.file)))
      if (!send({ type: 'message', agent_id: selectedAgentId.value, content: value, images: messageImages })) return
      clearImages()
    } catch (error) {
      sendError.value = error instanceof Error ? error.message : 'Could not upload images'
      return
    } finally {
      sending.value = false
    }
  }
  input.value = ''
  resizeInput()
}

function selectImages(event: Event) {
  const target = event.target as HTMLInputElement
  const selected = Array.from(target.files || []).slice(0, 8 - images.value.length)
  images.value.push(...selected.map(file => ({ file, url: URL.createObjectURL(file) })))
  target.value = ''
}

function removeImage(index: number) {
  const [image] = images.value.splice(index, 1)
  if (image) URL.revokeObjectURL(image.url)
}

function clearImages() {
  images.value.forEach(image => URL.revokeObjectURL(image.url))
  images.value = []
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
  clearImages()
})
</script>

<template>
  <div class="app-shell" :class="{ 'files-visible': filesOpen }">
    <div v-if="filesOpen" class="mobile-scrim" @click="filesOpen = false" />
    <FileBrowser v-if="filesOpen" :agents="agents" :agent-id="selectedAgentId" @close="filesOpen = false" />

    <main class="chat-shell">
      <header class="topbar">
        <div class="brand">
          <button class="icon-button file-toggle" :title="filesOpen ? 'Hide files' : 'Show files'" @click="filesOpen = !filesOpen">
            <PanelLeftClose v-if="filesOpen" :size="18" />
            <Files v-else :size="18" />
          </button>
          <div><h1>Xun</h1><span>Agent workspace</span></div>
        </div>
        <div class="agent-controls">
          <Bot :size="15" />
          <select v-model="selectedAgentId" aria-label="Active agent" :disabled="!agents.length">
            <option v-if="!agents.length" value="">No agents</option>
            <option v-for="agent in agents" :key="agent.identifier" :value="agent.identifier">{{ agent.name }}</option>
          </select>
          <label class="stream-filter" title="Show events from the active agent only">
            <input v-model="selectedOnly" type="checkbox">
            <span>Selected only</span>
          </label>
        </div>
        <div class="topbar-actions">
          <label class="markdown-toggle" title="Render messages as Markdown"><input v-model="markdown" type="checkbox"> MD</label>
          <span class="connection" :class="{ connected }"><Wifi v-if="connected" :size="14" /><WifiOff v-else :size="14" />{{ connected ? 'Connected' : 'Reconnecting' }}</span>
        </div>
      </header>

      <section ref="streamElement" class="conversation" aria-live="polite">
        <div v-if="!visibleEvents.length" class="empty-chat"><strong>{{ agents.length ? 'No activity here yet' : 'Waiting for an agent' }}</strong><span>{{ agents.length ? 'Send a message or show all agent activity.' : 'Bound agents will appear automatically.' }}</span></div>
        <EventStream v-else :events="visibleEvents" :markdown="markdown" />
      </section>

      <footer class="composer-area">
        <div class="composer-wrap">
          <div v-if="filteredCommands.length" class="command-menu">
            <button v-for="(command, index) in filteredCommands" :key="command.name" :class="{ selected: index === selectedCommand }" @mousedown.prevent="chooseCommand(command)">
              <code>/{{ command.name }}</code><span>{{ command.description }}</span>
            </button>
          </div>
          <div v-if="images.length" class="image-tray">
            <div v-for="(image, index) in images" :key="image.url" class="image-preview">
              <img :src="image.url" :alt="image.file.name">
              <button type="button" :title="`Remove ${image.file.name}`" @click="removeImage(index)"><X :size="13" /></button>
            </div>
          </div>
          <div class="composer">
            <input v-if="supportsVision" ref="imageInput" class="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple @change="selectImages">
            <button v-if="supportsVision" class="attach-button" type="button" title="Attach images" :disabled="sending || images.length >= 8" @click="imageInput?.click()"><ImagePlus :size="18" /></button>
            <textarea ref="textarea" v-model="input" rows="1" :placeholder="selectedAgent ? `Message ${selectedAgent.name}` : 'Select an agent to start'" :disabled="!connected || !selectedAgent" @input="resizeInput" @keydown="handleKeydown" />
            <button class="send-button" title="Send" :disabled="!connected || !selectedAgent || sending || (!input.trim() && !images.length)" @click="submit"><Send :size="18" /></button>
          </div>
          <span v-if="sendError" class="composer-error">{{ sendError }}</span>
          <span class="composer-hint">Enter to send · Shift+Enter for a new line</span>
        </div>
      </footer>
    </main>

    <PromptDialog v-if="pendingPrompt" :prompt="pendingPrompt" @submit="answerPrompt" />
  </div>
</template>
