<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PendingPrompt } from '../types'

const props = defineProps<{ prompt: PendingPrompt }>()
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
  <div class="dialog-backdrop">
    <section class="prompt-dialog" role="dialog" aria-modal="true" aria-labelledby="prompt-title">
      <span class="eyebrow">Agent request</span>
      <h2 id="prompt-title">{{ prompt.title || 'Choice required' }}</h2>
      <p v-if="prompt.subtitle" class="prompt-subtitle">{{ prompt.subtitle }}</p>
      <p>{{ prompt.message || prompt.prompt }}</p>
      <div class="prompt-choices">
        <button v-for="choice in prompt.choices" :key="choice" :class="{ selected: selected === choice }" @click="selected = choice">{{ choice }}</button>
      </div>
      <input v-if="prompt.allow_extra" v-model="extra" placeholder="Or enter another response" @keydown.enter="submit">
      <button class="primary-button" :disabled="!selected && !extra.trim()" @click="submit">Submit</button>
    </section>
  </div>
</template>
