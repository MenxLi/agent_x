<script setup lang="ts">
import { onBeforeUnmount } from 'vue'

const props = defineProps<{ orientation: 'horizontal' | 'vertical' }>()
const emit = defineEmits<{ drag: [delta: number]; reset: [] }>()

let handle: HTMLElement | null = null

function axis(event: PointerEvent) {
  return props.orientation === 'horizontal' ? event.clientX : event.clientY
}

function pointerdown(event: PointerEvent) {
  handle = event.currentTarget as HTMLElement
  handle.setPointerCapture(event.pointerId)
  document.body.classList.add(props.orientation === 'horizontal' ? 'resizing-x' : 'resizing-y')
  let last = axis(event)
  const move = (next: PointerEvent) => {
    const current = axis(next)
    emit('drag', current - last)
    last = current
  }
  const stop = () => {
    document.body.classList.remove('resizing-x', 'resizing-y')
    handle?.removeEventListener('pointermove', move)
    handle?.removeEventListener('pointerup', stop)
    handle?.removeEventListener('pointercancel', stop)
    handle = null
  }
  handle.addEventListener('pointermove', move)
  handle.addEventListener('pointerup', stop)
  handle.addEventListener('pointercancel', stop)
}

// Keyboard nudges the panel in 12px steps for accessibility.
function keydown(event: KeyboardEvent) {
  const back = props.orientation === 'horizontal' ? 'ArrowLeft' : 'ArrowUp'
  const forward = props.orientation === 'horizontal' ? 'ArrowRight' : 'ArrowDown'
  if (event.key === back) emit('drag', -12)
  else if (event.key === forward) emit('drag', 12)
  else return
  event.preventDefault()
}

onBeforeUnmount(() => document.body.classList.remove('resizing-x', 'resizing-y'))
</script>

<template>
  <div
    class="resize-handle"
    :class="orientation"
    role="separator"
    :aria-orientation="orientation"
    tabindex="0"
    @pointerdown.prevent="pointerdown"
    @dblclick="emit('reset')"
    @keydown="keydown"
  />
</template>
