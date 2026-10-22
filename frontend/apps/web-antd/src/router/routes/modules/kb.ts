import type { RouteRecordRaw } from 'vue-router';

/** 菜单分组外壳（仅承载子路由，不改变页面 URL） */
const PassThrough = () => import('#/layouts/pass-through.vue');

const routes: RouteRecordRaw[] = [
  // 兼容 Vben 默认 / 缓存首页（localStorage 可能仍指向 /dashboard）
  {
    name: 'DashboardRedirect',
    path: '/dashboard/:path(.*)*',
    redirect: '/kb/qa',
    meta: {
      hideInMenu: true,
      hideInTab: true,
      title: 'Redirect',
    },
  },
  {
    meta: {
      icon: 'lucide:library',
      order: -10,
      title: '知识库',
    },
    name: 'KnowledgeHub',
    path: '/kb',
    redirect: '/kb/qa',
    children: [
      /* —— 智能应用（叶子路径保持 /kb/*） —— */
      {
        component: PassThrough,
        meta: {
          icon: 'lucide:sparkles',
          order: 10,
          title: '智能应用',
        },
        name: 'KbApps',
        path: 'apps',
        redirect: '/kb/qa',
        children: [
          {
            name: 'KbQa',
            path: '/kb/qa',
            component: () => import('#/views/kb/qa/index.vue'),
            meta: {
              icon: 'lucide:messages-square',
              order: 1,
              title: '问答控制台',
            },
          },
          {
            name: 'KbGraph',
            path: '/kb/graph',
            component: () => import('#/views/kb/graph/index.vue'),
            meta: {
              icon: 'lucide:share-2',
              order: 2,
              title: '图谱总览',
            },
          },
          {
            name: 'KbImpact',
            path: '/kb/impact',
            component: () => import('#/views/kb/impact/index.vue'),
            meta: {
              icon: 'lucide:git-branch',
              order: 3,
              title: '影响分析与代码生成',
            },
          },
          {
            name: 'KbCodeTree',
            path: '/kb/code-tree',
            component: () => import('#/views/kb/code-tree/index.vue'),
            meta: {
              icon: 'lucide:folder-tree',
              order: 4,
              title: '代码树与注释',
            },
          },
        ],
      },

      /* —— 内容管理（叶子路径保持 /knowledge/*） —— */
      {
        component: PassThrough,
        meta: {
          icon: 'lucide:folder-kanban',
          order: 20,
          title: '内容管理',
        },
        name: 'KbContent',
        path: '/knowledge',
        redirect: '/knowledge/docs',
        children: [
          {
            name: 'KnowledgeDocs',
            path: 'docs',
            component: () => import('#/views/knowledge/docs/index.vue'),
            meta: {
              icon: 'lucide:library',
              order: 1,
              title: '知识库列表',
            },
          },
          {
            name: 'KnowledgeUpload',
            path: 'upload',
            component: () => import('#/views/knowledge/upload/index.vue'),
            meta: {
              icon: 'lucide:upload',
              order: 2,
              title: '上传文档',
            },
          },
          {
            name: 'KnowledgeChunk',
            path: 'chunk',
            component: () => import('#/views/knowledge/chunk/index.vue'),
            meta: {
              icon: 'lucide:scissors',
              order: 3,
              title: '切片查看',
            },
          },
          {
            name: 'KnowledgeDiff',
            path: 'diff',
            component: () => import('#/views/knowledge/diff/index.vue'),
            meta: {
              icon: 'lucide:git-compare',
              order: 4,
              title: '版本对比',
            },
          },
          {
            name: 'KnowledgeCodeMap',
            path: 'codemap',
            component: () => import('#/views/knowledge/codemap/index.vue'),
            meta: {
              icon: 'lucide:link-2',
              order: 5,
              title: '代码文档映射',
            },
          },
        ],
      },

      /* —— 构建与治理 —— */
      {
        component: PassThrough,
        meta: {
          icon: 'lucide:wrench',
          order: 30,
          title: '构建与治理',
        },
        name: 'KbOps',
        path: 'ops',
        redirect: '/kb/ingest',
        children: [
          {
            name: 'KbIngest',
            path: '/kb/ingest',
            component: () => import('#/views/kb/ingest/index.vue'),
            meta: {
              authority: ['gov', 'admin', 'dev'],
              icon: 'lucide:upload-cloud',
              order: 1,
              title: '知识接入',
            },
          },
          {
            name: 'KbGovernance',
            path: '/kb/governance',
            component: () => import('#/views/kb/governance/index.vue'),
            meta: {
              authority: ['gov', 'admin', 'biz', 'arch'],
              icon: 'lucide:clipboard-check',
              order: 2,
              title: '治理工作台',
            },
          },
        ],
      },

      {
        name: 'KbSystem',
        path: 'system',
        component: () => import('#/views/kb/system/index.vue'),
        meta: {
          icon: 'lucide:settings-2',
          order: 90,
          title: '系统状态',
        },
      },

      /* 兼容旧入口（不进菜单） */
      {
        name: 'KbAnnotate',
        path: 'annotate',
        redirect: '/kb/code-tree',
        meta: {
          hideInMenu: true,
          hideInTab: true,
          title: '代码注释',
        },
      },
      {
        name: 'KbPromptsLegacy',
        path: 'prompts',
        redirect: '/config/prompts',
        meta: {
          hideInMenu: true,
          hideInTab: true,
          title: '式样书提示词',
        },
      },
      {
        name: 'KnowledgeGraphAlias',
        path: '/knowledge/graph',
        redirect: '/kb/graph',
        meta: {
          hideInMenu: true,
          hideInTab: true,
          title: '知识图谱',
        },
      },
    ],
  },
  {
    meta: {
      authority: ['gov', 'admin'],
      icon: 'lucide:settings',
      order: -5,
      title: '配置',
    },
    name: 'Config',
    path: '/config',
    redirect: '/config/prompts',
    children: [
      {
        name: 'KbPrompts',
        path: 'prompts',
        component: () => import('#/views/kb/prompts/index.vue'),
        meta: {
          authority: ['gov', 'admin'],
          icon: 'lucide:scroll-text',
          title: '式样书提示词',
        },
      },
    ],
  },
];

export default routes;
