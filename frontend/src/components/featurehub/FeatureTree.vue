<template>
  <div class="feature-tree">
    <div class="feature-family-strip" role="tablist" aria-label="Feature field groups">
      <button
        v-for="group in grouped"
        :key="group.family"
        type="button"
        class="feature-family-tab"
        :class="{ active: group.family === activeFamily }"
        @click="activeFamily = group.family"
      >
        <span>{{ format(group.family) }}</span>
        <strong>{{ selectedInGroup(group) }}/{{ selectableCount(group) }}</strong>
      </button>
    </div>

    <div v-if="activeGroup" class="feature-tree-active-panel">
      <div class="feature-tree-toolbar">
        <div>
          <div class="eyebrow">Active group</div>
          <h4>{{ format(activeGroup.family) }} <span>{{ activeGroup.fields.length }} fields</span></h4>
        </div>
        <div class="row">
          <button class="btn subtle small-btn" type="button" @click="selectGroup(activeGroup)">Select eligible</button>
          <button class="btn subtle small-btn" type="button" @click="clearGroup(activeGroup)">Clear group</button>
        </div>
      </div>

      <div class="feature-tree-scroll">
        <label
          v-for="field in activeGroup.fields"
          :key="field.field"
          class="checkbox-inline feature-tree-row"
          :class="{ selected: selected.includes(field.field), disabled: isDisabled(field) }"
        >
          <input
            type="checkbox"
            :value="field.field"
            :checked="selected.includes(field.field)"
            @change="toggle(field.field)"
            :disabled="isDisabled(field)"
          />
          <span>{{ field.field }}</span>
          <FieldBadge :role="field.ml_role" :scope="field.scope" :text="field.scope === 'full' ? 'Full only' : field.ml_role" />
        </label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import FieldBadge from './FieldBadge.vue'

const props = defineProps({
  fields: { type: Array, default: () => [] },
  selected: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:selected'])
const activeFamily = ref('')

const grouped = computed(() => {
  const map = new Map()
  for (const field of props.fields) {
    const key = field.family || 'other'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(field)
  }
  return Array.from(map.entries()).map(([family, fields]) => ({ family, fields }))
})

const activeGroup = computed(() => grouped.value.find(group => group.family === activeFamily.value) || grouped.value[0])

watch(grouped, groups => {
  if (!groups.length) {
    activeFamily.value = ''
    return
  }
  if (!groups.some(group => group.family === activeFamily.value)) {
    activeFamily.value = groups[0].family
  }
}, { immediate: true })

function isDisabled(field) {
  return field.scope === 'full' || field.ml_role === 'exclude'
}

function toggle(field) {
  const next = props.selected.includes(field)
    ? props.selected.filter(item => item !== field)
    : [...props.selected, field]
  emit('update:selected', next)
}

function selectGroup(group) {
  const selectable = selectableFields(group)
  emit('update:selected', Array.from(new Set([...props.selected, ...selectable])))
}

function clearGroup(group) {
  const selectable = selectableFields(group)
  emit('update:selected', props.selected.filter(item => !selectable.includes(item)))
}

function selectableFields(group) {
  return group.fields.filter(item => !isDisabled(item)).map(item => item.field)
}

function selectableCount(group) {
  return selectableFields(group).length
}

function selectedInGroup(group) {
  return selectableFields(group).filter(item => props.selected.includes(item)).length
}

function format(value) {
  return String(value || '').replaceAll('_', ' ')
}
</script>
