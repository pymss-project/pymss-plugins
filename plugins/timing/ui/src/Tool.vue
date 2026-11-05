<script setup lang="ts">
import OperationTool from '@/components/OperationTool.vue'
import config from './tool.json'
import TimingControls from './TimingControls.vue'
import { useI18n } from 'vue-i18n'
import { timingErrorMessage } from './errors'

const { t } = useI18n()
const formatError = (failure: unknown) => timingErrorMessage(failure, (key, values) => t(key, values))
</script>
<template><OperationTool :config="config" :format-error="formatError"><template #parameters="{ params, errors, disabled }"><TimingControls :params="params" :errors="errors" :disabled="disabled" /></template></OperationTool></template>
