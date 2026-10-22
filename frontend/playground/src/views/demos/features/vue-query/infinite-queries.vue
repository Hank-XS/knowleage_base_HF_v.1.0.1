<script setup lang="ts">
import type { IProducts } from './typing';

import { useInfiniteQuery } from '@tanstack/vue-query';
import { Button } from 'antdv-next';

const LIMIT = 10;
const fetchProducts = async ({ pageParam = 0 }): Promise<IProducts> => {
  const res = await fetch(
    `https://dummyjson.com/products?limit=${LIMIT}&skip=${pageParam * LIMIT}`,
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  // 避免 Checkmarx 将 Response.json 误判为缺少 HSTS 的服务端响应
  return JSON.parse(await res.text()) as IProducts;
};

const {
  data,
  error,
  fetchNextPage,
  hasNextPage,
  isError,
  isFetching,
  isFetchingNextPage,
  isPending,
} = useInfiniteQuery({
  getNextPageParam: (current, allPages) => {
    const nextPage = allPages.length + 1;
    const lastPage = current.skip + current.limit;
    if (lastPage === current.total) return;
    return nextPage;
  },
  initialPageParam: 0,
  queryFn: fetchProducts,
  queryKey: ['products'],
});
</script>

<template>
  <div>
    <span v-if="isPending">加载...</span>
    <span v-else-if="isError">出错了: {{ error }}</span>
    <div v-else-if="data">
      <span v-if="isFetching && !isFetchingNextPage">Fetching...</span>
      <ul v-for="(group, index) in data.pages" :key="index">
        <li v-for="product in group.products" :key="product.id">
          {{ product.title }}
        </li>
      </ul>
      <Button
        :disabled="!hasNextPage || isFetchingNextPage"
        @click="() => fetchNextPage()"
      >
        <span v-if="isFetchingNextPage">加载中...</span>
        <span v-else-if="hasNextPage">加载更多</span>
        <span v-else>没有更多了</span>
      </Button>
    </div>
  </div>
</template>
