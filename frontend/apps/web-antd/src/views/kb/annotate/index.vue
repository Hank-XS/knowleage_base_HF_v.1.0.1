<script lang="ts" setup>
import { onMounted } from 'vue';
import { useRouter } from 'vue-router';

defineOptions({ name: 'KbAnnotateRedirect' });

const router = useRouter();
onMounted(() => {
  router.replace('/kb/code-tree');
});
</script>

<template>
  <div />
</template>
