<script setup lang="ts">
import { ref, watch } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import type { PendingPrompt } from '../types'

const props = defineProps<{ prompt: PendingPrompt; agentName?: string; submitting?: boolean; error?: string }>()
const emit = defineEmits<{ submit: [value: string] }>()
const selected = ref('')
const extra = ref('')

watch(() => props.prompt, prompt => {
  selected.value = prompt.default || ''
  extra.value = ''
}, { immediate: true })

function submit() {
  const value = extra.value.trim() || selected.value
  if (value) emit('submit', value)
}
</script>

<template>
  <section class="prompt-card" :aria-labelledby="`prompt-title-${prompt.id}`">
    <span class="eyebrow">{{ agentName ? `${agentName} is asking` : 'Agent request' }}</span>
    <h2 :id="`prompt-title-${prompt.id}`">{{ prompt.title || 'Choice required' }}</h2>
    <p v-if="prompt.subtitle" class="prompt-subtitle">{{ prompt.subtitle }}</p>
    <details v-if="(prompt.message || prompt.prompt).length > 500" class="prompt-message-long">
      <summary>View full request <ChevronDown :size="13" /></summary>
      <p>{{ prompt.message || prompt.prompt }}</p>
    </details>
    <p v-else>{{ prompt.message || prompt.prompt }}</p>
    <div class="prompt-choices">
      <button v-for="choice in prompt.choices" :key="choice" :class="{ selected: selected === choice }" @click="selected = choice">{{ choice }}</button>
    </div>
    <input v-if="prompt.allow_extra" v-model="extra" placeholder="Or enter another response" @keydown.enter="submit">
    <p v-if="error" class="prompt-error" role="alert">{{ error }}</p>
    <button class="primary-button" :disabled="submitting || (!selected && !extra.trim())" @click="submit">{{ submitting ? 'Submitting...' : 'Submit' }}</button>
  </section>
</template>