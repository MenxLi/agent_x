<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Bot, Check, Files, Monitor, Moon, PanelLeftClose, Settings, Sun, Wifi, WifiOff } from 'lucide-vue-next'
import { api, appUrl, formatTokens } from './api'
import InputComposer from './components/InputComposer.vue'
import EventStream from './components/EventStream.vue'
import FileBrowser from './components/FileBrowser.vue'
import PromptCard from './components/PromptCard.vue'
import type { AgentInfo, ClientMessage, CommandInfo, DisplayEvent, ImageDescriptor, PendingPrompt, ServerMessage } from './types'
import { useSettingsStore, type Theme } from './stores/settings'
import { useInputHistoryStore } from './stores/inputHistory'

const settings = useSettingsStore()
const inputHistory = useInputHistoryStore()

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
let socket: WebSocket | null = null
let reconnectTimer: number | undefined
let agentDataRequest = 0
let configLoaded = false
let syncing = false
let queuedMessages: ServerMessage[] = []

const selectedAgent = computed(() => agents.value.find(agent => agent.identifier === selectedAgentId.value))
const selectedAgentRunning = computed(() => runningAgents.value.has(selectedAgentId.value))
const selectedAgentCancelling = computed(() => cancellingAgents.value.has(selectedAgentId.value))
const visibleEvents = computed(() => selectedOnly.value && selectedAgentId.value
  ? events.value.filter(event => event.agent.identifier === selectedAgentId.value)
  : events.value,
)
const visiblePrompts = computed(() => selectedOnly.value && selectedAgentId.value
  ? pendingPrompts.value.filter(prompt => prompt.agent_id === selectedAgentId.value)
  : pendingPrompts.value,
)
const selectedAgentTokens = computed(() => {
  for (let i = events.value.length - 1; i >= 0; i--) {
    const event = events.value[i]
    if (event.name !== 'ModelMessageEvent' || event.agent.identifier !== selectedAgentId.value) continue
    return event.payload.total_tokens
  }
  return null
})

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
    if (send({ type: 'command', agent_id: selectedAgentId.value, name, arguments: argumentsParts.join(' ') || null })) inputHistory.add(value)
  } else {
    sending.value = true
    try {
      const messageImages = await Promise.all(images.value.map(image => readImage(image.file)))
      if (!send({ type: 'message', agent_id: selectedAgentId.value, content: value, images: messageImages })) return
      inputHistory.add(value)
      clearImages()
    } catch (error) {
      sendError.value = error instanceof Error ? error.message : 'Could not upload images'
      return
    } finally {
      sending.value = false
    }
  }
  input.value = ''
}

function cancelExecution() {
  const agentId = selectedAgentId.value
  if (!agentId || selectedAgentCancelling.value || !send({ type: 'cancel', agent_id: agentId })) return
  cancellingAgents.value = new Set(cancellingAgents.value).add(agentId)
}

function removeImage(index: number) {
  const [image] = images.value.splice(index, 1)
  if (image) URL.revokeObjectURL(image.url)
}

function clearImages() {
  images.value.forEach(image => URL.revokeObjectURL(image.url))
  images.value = []
}

function attachImages(files: File[]) {
  images.value.push(...files.map(file => ({ file, url: URL.createObjectURL(file) })))
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
          <span v-if="selectedAgentTokens != null" class="token-badge" title="Total tokens used by the active agent's conversation">{{ formatTokens(selectedAgentTokens) }} tokens</span>
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
        <InputComposer
          v-model="input"
          :commands="commands"
          :placeholder="selectedAgent ? `Message ${selectedAgent.name}` : 'Select an agent to start'"
          :disabled="!connected || !selectedAgent"
          :supports-vision="supportsVision"
          :images="images"
          :running="selectedAgentRunning"
          :cancelling="selectedAgentCancelling"
          :sending="sending"
          :error="sendError"
          @send="submit"
          @stop="cancelExecution"
          @attach="attachImages"
          @remove-image="removeImage"
        />
      </footer>

    </main>

  </div>
</template>
