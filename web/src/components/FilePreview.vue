<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Download, FileQuestion, X } from 'lucide-vue-next'
import { api } from '../api'
import { previewKind } from '../preview'
import type { FileEntry } from '../types'

const props = defineProps<{ agentId: string; entry: FileEntry }>()
const emit = defineEmits<{ close: [] }>()

const kind = computed(() => previewKind(props.entry.media_type))
const contentUrl = computed(() => api.contentUrl(props.agentId, props.entry.path))

const text = ref('')
const loading = ref(false)
const error = ref('')

watch(() => props.entry.path, () => {
  error.value = ''
  if (kind.value !== 'text') return
  loading.value = true
  text.value = ''
  api.textContent(props.agentId, props.entry.path)
    .then(value => { text.value = value })
    .catch(reason => { error.value = reason instanceof Error ? reason.message : 'Could not preview file' })
    .finally(() => { loading.value = false })
}, { immediate: true })
</script>

<template>
  <section class="file-preview">
    <header>
      <span>{{ entry.path }}</span>
      <div class="preview-actions">
        <a class="icon-button" :href="api.downloadUrl(agentId, entry.path)" :download="entry.name" title="Download"><Download :size="14" /></a>
        <button class="icon-button" title="Close preview" @click="emit('close')"><X :size="15" /></button>
      </div>
    </header>

    <template v-if="kind === 'image'">
      <img v-show="!error" :src="contentUrl" :alt="entry.name" @error="error = 'Could not load image'">
      <div v-if="error" class="preview-error">{{ error }}</div>
    </template>

    <template v-else-if="kind === 'text'">
      <div v-if="error" class="preview-error">{{ error }}</div>
      <pre v-else>{{ loading ? 'Loading…' : text }}</pre>
    </template>

    <div v-else class="preview-unsupported">
      <FileQuestion :size="20" />
      <span>No preview for {{ entry.media_type || 'this file' }}</span>
      <a class="preview-download" :href="api.downloadUrl(agentId, entry.path)" :download="entry.name">
        <Download :size="12" /> Download file
      </a>
    </div>
  </section>
</template>
