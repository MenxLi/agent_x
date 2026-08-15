<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Bot, Check, Files, ImagePlus, Monitor, Moon, PanelLeftClose, Send, Settings, Square, Sun, Wifi, WifiOff, X } from 'lucide-vue-next'
import { api, appUrl } from './api'
import EventStream from './components/EventStream.vue'
import FileBrowser from './components/FileBrowser.vue'
import PromptCard from './components/PromptCard.vue'
import type { AgentInfo, ClientMessage, CommandInfo, DisplayEvent, ImageDescriptor, PendingPrompt, ServerMessage } from './types'
import { useSettingsStore, type Theme } from './stores/settings'

const settings = useSettingsStore()

const events = ref<DisplayEvent[]>([])
const agents = ref<AgentInfo[]>([])
const selectedAgentId = ref('')
const selectedOnly = ref(false)
const commands = ref<CommandInfo[]>([])
const input = ref('')
const connected = ref(false)
const exposeFiles = ref(false)
const filesOpen = ref(false)
const settingsOpen = ref(false)
const selectedCommand = ref(0)
const pendingPrompts = ref<PendingPrompt[]>([])
const supportsVision = ref(false)
const images = ref<Array<{ file: File; url: string }>>([])
const sending = ref(false)
const runningAgents = ref(new Set<string>())
const cancellingAgents = ref(new Set<string>())
const sendError = ref('')
const promptErrors = ref(new Map<string, string>())
const resolvingPrompts = ref(new Set<string>())
const streamElement = ref<HTMLElement>()
const textarea = ref<HTMLTextAreaElement>()
const imageInput = ref<HTMLInputElement>()
let socket: WebSocket | null = null
let reconnectTimer: number | undefined
let agentDataRequest = 0
let configLoaded = false
let composing: boolean = false
let syncing = false
let queuedMessages: ServerMessage[] = []

const selectedAgent = computed(() => agents.value.find(agent => agent.identifier === selectedAgentId.value))
const selectedAgentRunning = computed(() => runningAgents.value.has(selectedAgentId.value))
const selectedAgentCancelling = computed(() => cancellingAgents.value.has(selectedAgentId.value))
const visibleEvents = computed(() => selectedOnly.value && selectedAgentId.value
  ? events.value.filter(event => event.agent?.identifier === selectedAgentId.value)
  : events.value,
)
const visiblePrompts = computed(() => selectedOnly.value && selectedAgentId.value
  ? pendingPrompts.value.filter(prompt => prompt.agent_id === selectedAgentId.value)
  : pendingPrompts.value,
)

const commandQuery = computed(() => {
  const match = input.value.match(/^\/([^\s]*)$/)
  return match ? match[1].toLowerCase() : null
})
const filteredCommands = computed(() => commandQuery.value === null ? [] : commands.value.filter(command =>
  command.name.toLowerCase().includes(commandQuery.value!) || command.description.toLowerCase().includes(commandQuery.value!),
))

watch(() => settings.theme, theme => {
  if (theme === 'system') delete document.documentElement.dataset.theme
  else document.documentElement.dataset.theme = theme
}, { immediate: true })
watch(events, () => nextTick(() => {
  if (streamElement.value) streamElement.value.scrollTop = streamElement.value.scrollHeight
}), { deep: true })
watch(pendingPrompts, () => nextTick(() => {
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
  const [config, eventData, agentData, runningData, promptData] = await Promise.all([
    api.config(), api.events(), api.agents(), api.running(), api.prompts(),
  ])
  exposeFiles.value = config.expose_files
  if (!configLoaded) filesOpen.value = config.expose_files && window.innerWidth >= 900
  else if (!config.expose_files) filesOpen.value = false
  configLoaded = true
  events.value = eventData
  agents.value = agentData
  runningAgents.value = new Set(runningData)
  pendingPrompts.value = promptData
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
    syncing = true
    await loadInitialData().catch(() => undefined)
    syncing = false
    queuedMessages.forEach(handleServerMessage)
    queuedMessages = []
  })
  socket.addEventListener('message', message => {
    const payload = JSON.parse(message.data) as ServerMessage
    if (syncing) queuedMessages.push(payload)
    else handleServerMessage(payload)
  })
  socket.addEventListener('close', () => {
    connected.value = false
    reconnectTimer = window.setTimeout(connect, 2500)
  })
}

function handleServerMessage(payload: ServerMessage) {
  if (isPendingPrompt(payload)) {
    pendingPrompts.value = [...pendingPrompts.value.filter(prompt => prompt.id !== payload.data.id), payload.data]
  } else if (isPromptResolved(payload)) {
    pendingPrompts.value = pendingPrompts.value.filter(prompt => prompt.id !== payload.prompt_id)
  } else if (isExecutionState(payload)) {
    const running = new Set(runningAgents.value)
    const cancelling = new Set(cancellingAgents.value)
    if (payload.running) {
      running.add(payload.agent_id)
      cancelling.delete(payload.agent_id)
    } else {
      running.delete(payload.agent_id)
      cancelling.delete(payload.agent_id)
    }
    runningAgents.value = running
    cancellingAgents.value = cancelling
  } else {
    applyAgentEvent(payload)
    events.value.push(payload)
  }
}

function isPendingPrompt(payload: ServerMessage): payload is Extract<ServerMessage, { type: 'pending_prompt' }> {
  return 'type' in payload && payload.type === 'pending_prompt'
}

function isPromptResolved(payload: ServerMessage): payload is Extract<ServerMessage, { type: 'prompt_resolved' }> {
  return 'type' in payload && payload.type === 'prompt_resolved'
}

function isExecutionState(payload: ServerMessage): payload is Extract<ServerMessage, { type: 'execution_state' }> {
  return 'type' in payload && payload.type === 'execution_state'
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
  if ((!value && !images.value.length) || !connected.value || !selectedAgentId.value || sending.value || selectedAgentRunning.value) return
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

function cancelExecution() {
  const agentId = selectedAgentId.value
  if (!agentId || selectedAgentCancelling.value || !send({ type: 'cancel', agent_id: agentId })) return
  cancellingAgents.value = new Set(cancellingAgents.value).add(agentId)
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

function handleCompositionStart() {
  composing = true
}

function handleCompositionEnd() {
  composing = false
}

function handleKeydown(event: KeyboardEvent) {
  if (composing || event.isComposing || event.keyCode === 229) return

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
    if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
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

async function answerPrompt(promptId: string, value: string) {
  resolvingPrompts.value = new Set(resolvingPrompts.value).add(promptId)
  promptErrors.value.delete(promptId)
  try {
    await api.resolvePrompt(promptId, value)
    pendingPrompts.value = pendingPrompts.value.filter(prompt => prompt.id !== promptId)
  } catch (error) {
    promptErrors.value.set(promptId, error instanceof Error ? error.message : 'Could not submit response')
    promptErrors.value = new Map(promptErrors.value)
  } finally {
    const resolving = new Set(resolvingPrompts.value)
    resolving.delete(promptId)
    resolvingPrompts.value = resolving
  }
}

const themeOptions: Array<{ value: Theme; label: string; icon: typeof Monitor }> = [
  { value: 'system', label: 'System', icon: Monitor },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
]

onMounted(connect)
onBeforeUnmount(() => {
  window.clearTimeout(reconnectTimer)
  socket?.close()
  clearImages()
})
</script>

<template>
  <div class="app-shell" :class="{ 'files-visible': exposeFiles && filesOpen }">
    <div v-if="exposeFiles && filesOpen" class="mobile-scrim" @click="filesOpen = false" />
    <FileBrowser v-if="exposeFiles && filesOpen" :agents="agents" :agent-id="selectedAgentId" @close="filesOpen = false" />

    <main class="chat-shell">
      <header class="topbar">
        <div class="brand">
          <button v-if="exposeFiles" class="icon-button file-toggle" :title="filesOpen ? 'Hide files' : 'Show files'" @click="filesOpen = !filesOpen">
            <PanelLeftClose v-if="filesOpen" :size="18" />
            <Files v-else :size="18" />
          </button>
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
          <span class="connection" :class="{ connected }"><Wifi v-if="connected" :size="14" /><WifiOff v-else :size="14" />{{ connected ? 'Connected' : 'Reconnecting' }}</span>
          <div class="settings-wrap">
            <button class="icon-button" title="Display settings" aria-label="Display settings" :aria-expanded="settingsOpen" @click="settingsOpen = !settingsOpen"><Settings :size="17" /></button>
            <div v-if="settingsOpen" class="settings-menu">
              <span class="settings-label">Theme</span>
              <div class="theme-options">
                <button v-for="option in themeOptions" :key="option.value" :class="{ selected: settings.theme === option.value }" @click="settings.theme = option.value">
                  <component :is="option.icon" :size="14" />{{ option.label }}<Check v-if="settings.theme === option.value" class="theme-check" :size="13" />
                </button>
              </div>
              <label class="setting-toggle"><span>Render Markdown</span><input v-model="settings.markdown" type="checkbox"></label>
            </div>
          </div>
        </div>
      </header>

      <section ref="streamElement" class="conversation" aria-live="polite">
        <div v-if="!visibleEvents.length && !visiblePrompts.length" class="empty-chat"><strong>{{ agents.length ? 'No activity here yet' : 'Waiting for an agent' }}</strong><span>{{ agents.length ? 'Send a message or show all agent activity.' : 'Bound agents will appear automatically.' }}</span></div>
        <EventStream v-if="visibleEvents.length" :events="visibleEvents" :markdown="settings.markdown" />
        <div v-if="visiblePrompts.length" class="prompt-stream">
          <PromptCard
            v-for="prompt in visiblePrompts"
            :key="prompt.id"
            :prompt="prompt"
            :agent-name="agents.find(agent => agent.identifier === prompt.agent_id)?.name"
            :submitting="resolvingPrompts.has(prompt.id)"
            :error="promptErrors.get(prompt.id)"
            @submit="value => answerPrompt(prompt.id, value)"
          />
        </div>
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
            <button v-if="supportsVision" class="attach-button" type="button" title="Attach images" :disabled="sending || selectedAgentRunning || images.length >= 8" @click="imageInput?.click()"><ImagePlus :size="18" /></button>
            <textarea ref="textarea" v-model="input" rows="1" :placeholder="selectedAgent ? `Message ${selectedAgent.name}` : 'Select an agent to start'" :disabled="!connected || !selectedAgent" @input="resizeInput" @compositionstart="handleCompositionStart" @compositionend="handleCompositionEnd" @keydown="handleKeydown" />
            <button v-if="selectedAgentRunning" class="stop-button" :title="selectedAgentCancelling ? 'Cancelling' : 'Stop'" :disabled="selectedAgentCancelling" @click="cancelExecution"><Square :size="15" fill="currentColor" /></button>
            <button v-else class="send-button" title="Send" :disabled="!connected || !selectedAgent || sending || (!input.trim() && !images.length)" @click="submit"><Send :size="18" /></button>
          </div>
          <span v-if="sendError" class="composer-error">{{ sendError }}</span>
          <span class="composer-hint">{{ selectedAgentCancelling ? 'Cancelling execution...' : 'Enter to send · Shift+Enter for a new line' }}</span>
        </div>
      </footer>
    </main>

  </div>
</template>
