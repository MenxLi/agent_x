<script setup lang="ts">
import { ChevronRight, Scale } from 'lucide-vue-next'
import { eventTime, fullEventTime } from '../api'
import type { ConfirmDisplayEvent } from '../types'

defineProps<{ event: ConfirmDisplayEvent }>()
</script>

<template>
  <details class="confirm-hint">
    <summary>
      <Scale :size="12" class="confirm-icon" />
      <span>{{ event.payload.source === 'auto' ? 'Auto-confirmed' : 'Confirmed' }}</span>
      <span v-if="event.payload.choice" class="confirm-pick" :title="event.payload.choice">{{ event.payload.choice }}</span>
      <time :title="fullEventTime(event)">{{ eventTime(event) }}</time>
      <ChevronRight :size="10" class="chevron" />
    </summary>
    <dl>
      <div class="confirm-choices"><dt>Choices</dt><dd><span v-for="choice in event.payload.choices" :key="choice" class="confirm-choice" :class="{ selected: choice === event.payload.choice }">{{ choice }}</span></dd></div>
      <div v-if="event.payload.message" class="confirm-message-block"><dt>Message</dt><dd class="confirm-message">{{ event.payload.message }}</dd></div>
      <div><dt>Source</dt><dd>{{ event.payload.source }}</dd></div>
      <div><dt>Prompt</dt><dd>{{ event.payload.prompt }}</dd></div>
    </dl>
  </details>
</template>
