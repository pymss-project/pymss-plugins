<script setup lang="ts">
import OperationTool from '@/components/OperationTool.vue'
import config from './tool.json'
import TimingControls from './TimingControls.vue'
</script>
<template><OperationTool :config="config"><template #parameters="{ params, errors, disabled }"><TimingControls :params="params" :errors="errors" :disabled="disabled" /></template></OperationTool></template>
