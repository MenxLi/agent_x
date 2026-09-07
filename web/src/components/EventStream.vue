<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, ChevronRight, CircleAlert, Clock3, Copy, Link2, Link2Off, Terminal, Wrench } from 'lucide-vue-next'
import MarkdownText from './MarkdownText.vue'
import { formatTokens } from '../api'
import { copyText } from '../clipboard'
import type { DisplayEvent, ToolCallDisplayEvent, ToolResultDisplayEvent } from '../types'

const props = defineProps<{ events: DisplayEvent[]; markdown: boolean }>()

type StreamItem =
  | { kind: 'event'; key: string; data: DisplayEvent }
  | { kind: 'activity'; key: string; tools: ToolItem[] }

type ToolItem = { key: string; call: ToolCallDisplayEvent; result?: ToolResultDisplayEvent }

const items = computed<StreamItem[]>(() => {
  const output: StreamItem[] = []
  const tools = new Map<string, ToolItem>()
  props.events.forEach((data, index) => {
    if (data.name === 'ToolCallEvent') {
      const id = data.payload.tool_call_id
      const item: ToolItem = { key: id || `tool-${index}`, call: data }
      const previous = output.at(-1)
      if (previous?.kind === 'activity') previous.tools.push(item)
      else output.push({ kind: 'activity', key: `activity-${item.key}`, tools: [item] })
      if (id) tools.set(id, item)
    } else if (data.name === 'ToolResultEvent' && tools.has(data.payload.tool_call_id)) {
      tools.get(data.payload.tool_call_id)!.result = data
    } else if (data.name !== 'ModelWorkingEvent' || index === props.events.length - 1) {
      output.push({ kind: 'event', key: `${data.name}-${index}`, data })
    }
  })
  return output
})

type NoticeEvent = Extract<DisplayEvent, { name: 'InfoEvent' | 'WarningEvent' | 'ErrorEvent' }>

function isPlainTextEvent(event: DisplayEvent): event is NoticeEvent {
  return event.name === 'InfoEvent' || event.name === 'WarningEvent' || event.name === 'ErrorEvent'
}

function text(event: DisplayEvent): string {
  if (event.name === 'UserMessageEvent') return event.payload.content
  if (event.name === 'ModelMessageEvent') return event.payload.content
  if (isPlainTextEvent(event)) return event.payload.message
  return JSON.stringify(event.payload, null, 2)
}

function label(event: DisplayEvent): string {
  if (event.name === 'ModelMessageEvent') return event.agent.name
  if (event.name === 'UserCommandEvent') return 'Command'
  return event.name.replace(/Event$/, '').replace(/([a-z])([A-Z])/g, '$1 $2')
}

function isUser(event: DisplayEvent): boolean {
  return event.name === 'UserMessageEvent' || (event.name === 'InfoEvent' && event.payload.message.startsWith('[user] '))
}

function displayText(event: DisplayEvent): string {
  const value = text(event)
  return event.name === 'InfoEvent' && isUser(event) ? value.slice(7) : value
}

function eventTime(event: DisplayEvent): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(event.timestamp * 1000)
}

function fullEventTime(event: DisplayEvent): string {
  return new Date(event.timestamp * 1000).toLocaleString()
}

const copiedKey = ref('')
let copyTimer = 0

async function copyMessage(key: string, event: DisplayEvent) {
  await copyText(displayText(event))
  copiedKey.value = key
  window.clearTimeout(copyTimer)
  copyTimer = window.setTimeout(() => { copiedKey.value = '' }, 1600)
}

</script>

<template>
  <div class="stream">
    <template v-for="item in items" :key="item.key">
      <details v-if="item.kind === 'activity'" class="activity-group">
        <summary>
          <ChevronRight :size="14" class="chevron" />
          <span>Activity · {{ item.tools.length }} {{ item.tools.length === 1 ? 'step' : 'steps' }}</span>
          <span v-if="item.tools.some(tool => !tool.result)" class="tool-state">
            <Clock3 :size="12" />
            Running
          </span>
        </summary>
        <div class="activity-list">
          <details v-for="tool in item.tools" :key="tool.key" class="tool-row">
            <summary><ChevronRight :size="13" class="chevron" /><span>{{ tool.call.payload.tool_name || 'Tool' }}</span><time :title="fullEventTime(tool.call)">{{ eventTime(tool.call) }}</time></summary>
            <div class="tool-detail">
              <span>Input</span><pre>{{ JSON.stringify(tool.call.payload.args, null, 2) }}</pre>
              <template v-if="tool.result"><span>Output</span><pre>{{ JSON.stringify(tool.result.payload.result, null, 2) }}</pre></template>
            </div>
          </details>
        </div>
      </details>

      <template v-else>
        <div v-if="item.data.name === 'AgentBindEvent' || item.data.name === 'AgentUnbindEvent'" class="agent-lifecycle">
          <Link2 v-if="item.data.name === 'AgentBindEvent'" :size="12" />
          <Link2Off v-else :size="12" />
          <span>{{ item.data.agent.name }}</span>
          {{ item.data.name === 'AgentBindEvent' ? 'joined' : 'left' }}
          <time :title="fullEventTime(item.data)">{{ eventTime(item.data) }}</time>
        </div>

        <div v-else-if="item.data.name === 'ModelWorkingEvent'" class="working">
          <span class="working-dot" /> {{ item.data.agent.name }} is working
        </div>

        <details v-else-if="item.data.name === 'ConfirmEvent'" class="confirm-hint">
          <summary>
            <ChevronRight :size="12" class="chevron" />
            <span>{{ item.data.payload.source === 'auto' ? 'Auto-confirmed' : 'Confirmed' }}</span>
            <time :title="fullEventTime(item.data)">{{ eventTime(item.data) }}</time>
          </summary>
          <dl>
            <div class="confirm-choices"><dt>Choices</dt><dd><span v-for="choice in item.data.payload.choices" :key="choice" class="confirm-choice" :class="{ selected: choice === item.data.payload.choice }">{{ choice }}</span></dd></div>
            <div><dt>Source</dt><dd>{{ item.data.payload.source }}</dd></div>
            <div><dt>Prompt</dt><dd>{{ item.data.payload.prompt }}</dd></div>
          </dl>
        </details>

        <section v-else-if="item.data.name === 'ShowHelpEvent'" class="command-result">
          <header><Terminal :size="15" /> Available commands</header>
          <div v-for="command in item.data.payload.commands" :key="command.name" class="command-line">
            <code>/{{ command.name }}</code><span>{{ command.description }}</span>
          </div>
        </section>

        <section v-else-if="item.data.name === 'ShowToolsEvent'" class="tools-result">
          <header><Wrench :size="15" /> Tools <span>{{ item.data.payload.tools.length }}</span></header>
          <div v-if="!item.data.payload.tools.length" class="tools-empty">No tools registered.</div>
          <div v-for="tool in item.data.payload.tools" v-else :key="tool.name" class="tool-listing">
            <div class="tool-listing-name">
              <code>{{ tool.name }}</code>
              <span v-for="capability in tool.required_capabilities" :key="capability" class="capability-chip">{{ capability }}</span>
            </div>
            <p>{{ tool.description || 'No description provided.' }}</p>
          </div>
        </section>

        <section v-else-if="item.data.name === 'ShowHistoryEvent'" class="history-result">
          <header>Conversation history</header>
          <div v-for="(message, index) in item.data.payload.history" :key="index" class="history-line">
            <span>{{ message.role }}</span>
            <pre>{{ typeof message.content === 'string' ? message.content : JSON.stringify(message.content, null, 2) }}</pre>
          </div>
        </section>

        <div v-else-if="item.data.name === 'UserCommandEvent'" class="command-invocation">
          <Terminal :size="13" /> /{{ item.data.payload.name }}<span v-if="item.data.payload.arguments"> {{ item.data.payload.arguments }}</span>
        </div>

        <article v-else class="message" :class="{
          user: isUser(item.data),
          error: item.data.name === 'ErrorEvent',
          warning: item.data.name === 'WarningEvent',
          notice: item.data.name === 'InfoEvent' && !isUser(item.data),
        }">
          <div class="message-label">
            <CircleAlert v-if="item.data.name === 'ErrorEvent'" :size="13" />
            {{ isUser(item.data) ? 'You' : label(item.data) }}
            <template v-if="item.data.name === 'UserMessageEvent'">
              <span class="message-recipient">to</span> {{ item.data.agent.name }}
            </template>
            <template v-if="item.data.name === 'ModelMessageEvent'">
              <span class="message-recipient">·</span>
              <span class="token-usage" title="Total tokens used in this conversation">{{ formatTokens(item.data.payload.total_tokens) }} tokens</span>
            </template>
            <time :title="fullEventTime(item.data)">{{ eventTime(item.data) }}</time>
            <button
              type="button"
              class="message-copy"
              title="Copy message"
              :class="{ copied: copiedKey === item.key }"
              @click="copyMessage(item.key, item.data)"
            >
              <Copy v-if="copiedKey !== item.key" :size="12" />
              <Check v-else :size="12" />
            </button>
          </div>
          <details v-if="item.data.name === 'ModelMessageEvent' && item.data.payload.reasoning" class="reasoning">
            <summary><ChevronRight :size="11" class="chevron" />Reasoning</summary>
            <MarkdownText :content="item.data.payload.reasoning" :enabled="markdown" />
          </details>
          <MarkdownText v-if="displayText(item.data)" :content="displayText(item.data)" :enabled="markdown" :plain="isPlainTextEvent(item.data)" />
          <div v-if="item.data.name === 'UserMessageEvent' && item.data.payload.images.length" class="message-images">
            <a v-for="image in item.data.payload.images" :key="image.value" :href="image.value" target="_blank" rel="noopener noreferrer">
              <img :src="image.value" alt="Attached image">
            </a>
          </div>
        </article>
      </template>
    </template>
  </div>
</template>
