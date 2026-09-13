<script setup lang="ts">
export interface WizardStep {
  key: string
  label: string
}

defineProps<{
  steps: WizardStep[]
  currentIndex: number
  unlockedUpTo: number
}>()
const emit = defineEmits<{ (e: 'select-step', index: number): void }>()

function status(index: number, currentIndex: number, unlockedUpTo: number): 'done' | 'current' | 'locked' {
  if (index === currentIndex) return 'current'
  if (index <= unlockedUpTo) return 'done'
  return 'locked'
}

function select(index: number, unlockedUpTo: number) {
  if (index <= unlockedUpTo) emit('select-step', index)
}
</script>

<template>
  <nav class="wizard-stepper">
    <template v-for="(step, index) in steps" :key="step.key">
      <button
        type="button"
        class="wizard-step"
        :class="status(index, currentIndex, unlockedUpTo)"
        :disabled="index > unlockedUpTo"
        @click="select(index, unlockedUpTo)"
      >
        <span class="badge">
          <span v-if="status(index, currentIndex, unlockedUpTo) === 'done'" class="check">✓</span>
          <span v-else>{{ index + 1 }}</span>
        </span>
        <span class="label">{{ step.label }}</span>
      </button>
      <span v-if="index < steps.length - 1" class="connector" />
    </template>
  </nav>
</template>

<style scoped>
.wizard-stepper {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  padding: 10px 16px;
  margin-bottom: 18px;
  overflow-x: auto;
}

.wizard-step {
  display: flex;
  align-items: center;
  gap: 8px;
  border: none;
  background: none;
  padding: 6px 10px;
  border-radius: 20px;
  font-size: 13px;
  white-space: nowrap;
  cursor: pointer;
  color: #6b7686;
}

.wizard-step.current {
  background: #0b3d91;
  color: #ffffff;
  font-weight: 700;
}

.wizard-step.done {
  color: #1a7f4b;
}

.wizard-step.locked {
  color: #b9c6e0;
  cursor: not-allowed;
}

.badge {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1.5px solid currentColor;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 800;
  flex-shrink: 0;
}

.wizard-step.current .badge {
  background: #ffd400;
  border-color: #ffd400;
  color: #0b3d91;
}

.check {
  font-weight: 900;
}

.connector {
  width: 20px;
  height: 1px;
  background: #e3e8f0;
  flex-shrink: 0;
}
</style>
