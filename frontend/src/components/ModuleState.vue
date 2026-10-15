<template>
  <div class="module-state" :class="`module-state-${state}`" role="status" aria-live="polite">
    <template v-if="state === 'loading'">
      <span class="module-state-spinner" aria-hidden="true"></span>
      <div class="module-state-copy">
        <div class="module-state-kicker">Loading data</div>
        <h4>{{ title || 'Loading module data' }}</h4>
        <p>{{ message || 'The platform is retrieving the module payload.' }}</p>
        <div class="module-state-skeleton" aria-hidden="true"><i></i><i></i><i></i></div>
      </div>
    </template>

    <template v-else-if="state === 'error'">
      <span class="module-state-icon" aria-hidden="true">!</span>
      <div class="module-state-copy">
        <div class="module-state-kicker">Request error</div>
        <h4>{{ title || 'Module unavailable' }}</h4>
        <p>{{ message || 'The module request did not complete successfully.' }}</p>
        <button v-if="retry" class="module-state-action" type="button" @click="retry">Retry</button>
      </div>
    </template>

    <template v-else>
      <span class="module-state-icon" aria-hidden="true">i</span>
      <div class="module-state-copy">
        <div class="module-state-kicker">{{ state === 'limited' ? 'Partially available' : 'No data' }}</div>
        <h4>{{ title || (state === 'limited' ? 'Module is only partially populated' : 'No data to display') }}</h4>
        <p>{{ message || 'The current module has no renderable payload.' }}</p>
        <p v-if="suggestion" class="module-state-suggestion">{{ suggestion }}</p>
      </div>
    </template>
  </div>
</template>

<script setup>
defineProps({
  state: { type: String, default: 'missing' },
  title: { type: String, default: '' },
  message: { type: String, default: '' },
  suggestion: { type: String, default: '' },
  retry: { type: Function, default: null },
})
</script>
