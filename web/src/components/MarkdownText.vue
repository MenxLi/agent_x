<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

const props = defineProps<{ content: string; enabled: boolean; plain?: boolean }>()
const html = computed(() => props.plain ? '' : DOMPurify.sanitize(marked.parse(props.content, { async: false }) as string))
</script>

<template>
  <div v-if="!plain && enabled" class="markdown" v-html="html" />
  <div v-else class="plain-text">{{ content }}</div>
</template>
