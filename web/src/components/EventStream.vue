<script setup lang="ts">
import { computed } from 'vue'
import { Check, ChevronRight, CircleAlert, Clock3, Terminal } from 'lucide-vue-next'
import MarkdownText from './MarkdownText.vue'
import type { DisplayEvent } from '../types'

const props = defineProps<{ events: DisplayEvent[]; markdown: boolean }>()

type StreamItem =
  | { kind: 'event'; key: string; data: DisplayEvent }
  | { kind: 'tool'; key: string; call: DisplayEvent; result?: DisplayEvent }

const items = computed<StreamItem[]>(() => {
  const output: StreamItem[] = []
  const tools = new Map<string, Extract<StreamItem, { kind: 'tool' }>>()
  props.events.forEach((data, index) => {
    const id = String(data.event.tool_call_id || '')
    if (data.name === 'ToolCallEvent') {
      const item: Extract<StreamItem, { kind: 'tool' }> = { kind: 'tool', key: id || `tool-${index}`, call: data }
      output.push(item)
      if (id) tools.set(id, item)
    } else if (data.name === 'ToolResultEvent' && tools.has(id)) {
      tools.get(id)!.result = data
    } else if (data.name !== 'ModelWorkingEvent' || index === props.events.length - 1) {
      output.push({ kind: 'event', key: `${data.name}-${index}`, data })
    }
  })
  return output
})

function text(event: DisplayEvent): string {
  if (event.name === 'ModelMessageEvent') return String(event.event.content || '')
  if (event.name.endsWith('Event') && 'message' in event.event) return String(event.event.message || '')
  return JSON.stringify(event.event, null, 2)
}

function label(event: DisplayEvent): string {
  if (event.name === 'ModelMessageEvent') return event.agent?.name || 'Assistant'
  if (event.name === 'CommandEvent') return 'Command'
  return event.name.replace(/Event$/, '').replace(/([a-z])([A-Z])/g, '$1 $2')
}

function isUser(event: DisplayEvent): boolean {
  return event.name === 'InfoEvent' && String(event.event.message || '').startsWith('[user] ')
}

function displayText(event: DisplayEvent): string {
  const value = text(event)
  return isUser(event) ? value.slice(7) : value
}

function history(event: DisplayEvent): Array<Record<string, unknown>> {
  return Array.isArray(event.event.history) ? event.event.history as Array<Record<string, unknown>> : []
}

function commands(event: DisplayEvent): Array<{ name: string; description: string }> {
  return Array.isArray(event.event.commands) ? event.event.commands as Array<{ name: string; description: string }> : []
}
</script>

<template>
  <div class="stream">
    <template v-for="item in items" :key="item.key">
      <details v-if="item.kind === 'tool'" class="tool-row">
        <summary>
          <ChevronRight :size="14" class="chevron" />
          <span>{{ item.call.event.tool_name || 'Tool' }}</span>
          <span class="tool-state" :class="{ complete: item.result }">
            <Check v-if="item.result" :size="12" />
            <Clock3 v-else :size="12" />
            {{ item.result ? 'Complete' : 'Running' }}
          </span>
        </summary>
        <div class="tool-detail">
          <span>Input</span><pre>{{ JSON.stringify(item.call.event.args, null, 2) }}</pre>
          <template v-if="item.result">
            <span>Output</span><pre>{{ JSON.stringify(item.result.event.result, null, 2) }}</pre>
          </template>
        </div>
      </details>

      <template v-else>
        <div v-if="item.data.name === 'ModelWorkingEvent'" class="working">
          <span class="working-dot" /> {{ item.data.agent?.name || 'Agent' }} is working
        </div>

        <section v-else-if="item.data.name === 'ShowHelpEvent'" class="command-result">
          <header><Terminal :size="15" /> Available commands</header>
          <div v-for="command in commands(item.data)" :key="command.name" class="command-line">
            <code>/{{ command.name }}</code><span>{{ command.description }}</span>
          </div>
        </section>

        <section v-else-if="item.data.name === 'ShowHistoryEvent'" class="history-result">
          <header>Conversation history</header>
          <div v-for="(message, index) in history(item.data)" :key="index" class="history-line">
            <span>{{ message.role }}</span>
            <pre>{{ typeof message.content === 'string' ? message.content : JSON.stringify(message.content, null, 2) }}</pre>
          </div>
        </section>

        <div v-else-if="item.data.name === 'CommandEvent'" class="command-invocation">
          <Terminal :size="13" /> /{{ item.data.event.name }}<span v-if="item.data.event.arguments"> {{ item.data.event.arguments }}</span>
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
          </div>
          <MarkdownText :content="displayText(item.data)" :enabled="markdown" />
        </article>
      </template>
    </template>
  </div>
</template>
