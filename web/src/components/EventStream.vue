<script setup lang="ts">
import { computed } from 'vue'
import { Check, ChevronRight, CircleAlert, Clock3, Link2, Link2Off, Terminal, Wrench } from 'lucide-vue-next'
import MarkdownText from './MarkdownText.vue'
import type { DisplayEvent, ToolCallDisplayEvent, ToolResultDisplayEvent } from '../types'

const props = defineProps<{ events: DisplayEvent[]; markdown: boolean }>()

type StreamItem =
  | { kind: 'event'; key: string; data: DisplayEvent }
  | { kind: 'tool'; key: string; call: ToolCallDisplayEvent; result?: ToolResultDisplayEvent }

const items = computed<StreamItem[]>(() => {
  const output: StreamItem[] = []
  const tools = new Map<string, Extract<StreamItem, { kind: 'tool' }>>()
  props.events.forEach((data, index) => {
    if (data.name === 'ToolCallEvent') {
      const id = data.event.tool_call_id
      const item: Extract<StreamItem, { kind: 'tool' }> = { kind: 'tool', key: id || `tool-${index}`, call: data }
      output.push(item)
      if (id) tools.set(id, item)
    } else if (data.name === 'ToolResultEvent' && tools.has(data.event.tool_call_id)) {
      tools.get(data.event.tool_call_id)!.result = data
    } else if (data.name !== 'ModelWorkingEvent' || index === props.events.length - 1) {
      output.push({ kind: 'event', key: `${data.name}-${index}`, data })
    }
  })
  return output
})

function text(event: DisplayEvent): string {
  if (event.name === 'UserMessageEvent') return event.event.content
  if (event.name === 'ModelMessageEvent') return event.event.content
  if (event.name === 'InfoEvent' || event.name === 'WarningEvent' || event.name === 'ErrorEvent') return event.event.message
  return JSON.stringify(event.event, null, 2)
}

function label(event: DisplayEvent): string {
  if (event.name === 'ModelMessageEvent') return event.agent?.name || 'Assistant'
  if (event.name === 'UserCommandEvent') return 'Command'
  return event.name.replace(/Event$/, '').replace(/([a-z])([A-Z])/g, '$1 $2')
}

function isUser(event: DisplayEvent): boolean {
  return event.name === 'UserMessageEvent' || (event.name === 'InfoEvent' && event.event.message.startsWith('[user] '))
}

function displayText(event: DisplayEvent): string {
  const value = text(event)
  return event.name === 'InfoEvent' && isUser(event) ? value.slice(7) : value
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
        <div v-if="item.data.name === 'AgentBindEvent' || item.data.name === 'AgentUnbindEvent'" class="agent-lifecycle">
          <Link2 v-if="item.data.name === 'AgentBindEvent'" :size="12" />
          <Link2Off v-else :size="12" />
          <span>{{ item.data.agent?.name || 'Agent' }}</span>
          {{ item.data.name === 'AgentBindEvent' ? 'joined' : 'left' }}
        </div>

        <div v-else-if="item.data.name === 'ModelWorkingEvent'" class="working">
          <span class="working-dot" /> {{ item.data.agent?.name || 'Agent' }} is working
        </div>

        <section v-else-if="item.data.name === 'ShowHelpEvent'" class="command-result">
          <header><Terminal :size="15" /> Available commands</header>
          <div v-for="command in item.data.event.commands" :key="command.name" class="command-line">
            <code>/{{ command.name }}</code><span>{{ command.description }}</span>
          </div>
        </section>

        <section v-else-if="item.data.name === 'ShowToolsEvent'" class="tools-result">
          <header><Wrench :size="15" /> Tools <span>{{ item.data.event.tools.length }}</span></header>
          <div v-if="!item.data.event.tools.length" class="tools-empty">No tools registered.</div>
          <div v-for="tool in item.data.event.tools" v-else :key="tool.name" class="tool-listing">
            <div class="tool-listing-name">
              <code>{{ tool.name }}</code>
              <span v-for="capability in tool.required_capabilities" :key="capability" class="capability-chip">{{ capability }}</span>
            </div>
            <p>{{ tool.description || 'No description provided.' }}</p>
          </div>
        </section>

        <section v-else-if="item.data.name === 'ShowHistoryEvent'" class="history-result">
          <header>Conversation history</header>
          <div v-for="(message, index) in item.data.event.history" :key="index" class="history-line">
            <span>{{ message.role }}</span>
            <pre>{{ typeof message.content === 'string' ? message.content : JSON.stringify(message.content, null, 2) }}</pre>
          </div>
        </section>

        <div v-else-if="item.data.name === 'UserCommandEvent'" class="command-invocation">
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
            <template v-if="item.data.name === 'UserMessageEvent' && item.data.agent">
              <span class="message-recipient">to</span> {{ item.data.agent.name }}
            </template>
          </div>
          <MarkdownText v-if="displayText(item.data)" :content="displayText(item.data)" :enabled="markdown" />
          <div v-if="item.data.name === 'UserMessageEvent' && item.data.event.images.length" class="message-images">
            <a v-for="image in item.data.event.images" :key="image.value" :href="image.value" target="_blank" rel="noopener noreferrer">
              <img :src="image.value" alt="Attached image">
            </a>
          </div>
        </article>
      </template>
    </template>
  </div>
</template>
