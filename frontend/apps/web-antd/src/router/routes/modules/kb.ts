import type { RouteRecordRaw } from 'vue-router';

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
      icon: 'lucide:folder-kanban',
      order: -11,
      title: '知识库管理',
    },
    name: 'KnowledgeManage',
    path: '/knowledge',
    redirect: '/knowledge/docs',
    children: [
      {
        name: 'KnowledgeDocs',
        path: 'docs',
        component: () => import('#/views/knowledge/docs/index.vue'),
        meta: {
          icon: 'lucide:library',
          title: '知识库列表',
        },
      },
      {
        name: 'KnowledgeUpload',
        path: 'upload',
        component: () => import('#/views/knowledge/upload/index.vue'),
        meta: {
          icon: 'lucide:upload',
          title: '上传文档',
        },
      },
      {
        name: 'KnowledgeChunk',
        path: 'chunk',
        component: () => import('#/views/knowledge/chunk/index.vue'),
        meta: {
          icon: 'lucide:scissors',
          title: '切片查看',
        },
      },
      {
        name: 'KnowledgeDiff',
        path: 'diff',
        component: () => import('#/views/knowledge/diff/index.vue'),
        meta: {
          icon: 'lucide:git-compare',
          title: '版本对比',
        },
      },
      {
        name: 'KnowledgeCodeMap',
        path: 'codemap',
        component: () => import('#/views/knowledge/codemap/index.vue'),
        meta: {
          icon: 'lucide:link-2',
          title: '代码文档映射',
        },
      },
      {
        name: 'KnowledgeGraphAlias',
        path: 'graph',
        redirect: '/kb/graph',
        meta: {
          icon: 'lucide:share-2',
          title: '知识图谱',
        },
      },
    ],
  },
  {
    meta: {
      icon: 'lucide:database',
      order: -10,
      title: '知识库平台',
    },
    name: 'KnowledgeBase',
    path: '/kb',
    children: [
      {
        name: 'KbQa',
        path: 'qa',
        component: () => import('#/views/kb/qa/index.vue'),
        meta: {
          icon: 'lucide:messages-square',
          title: '问答控制台',
        },
      },
      {
        name: 'KbGraph',
        path: 'graph',
        component: () => import('#/views/kb/graph/index.vue'),
        meta: {
          icon: 'lucide:share-2',
          title: '图谱总览',
        },
      },
      {
        name: 'KbGovernance',
        path: 'governance',
        component: () => import('#/views/kb/governance/index.vue'),
        meta: {
          // 与 /user/info 返回的 roles（gov/admin/biz/arch）匹配；
          // 接口侧由后端 require_roles 双重校验
          authority: ['gov', 'admin', 'biz', 'arch'],
          icon: 'lucide:clipboard-check',
          title: '治理工作台',
        },
      },
      {
        name: 'KbIngest',
        path: 'ingest',
        component: () => import('#/views/kb/ingest/index.vue'),
        meta: {
          authority: ['gov', 'admin', 'dev'],
          icon: 'lucide:upload-cloud',
          title: '知识接入',
        },
      },
      {
        name: 'KbImpact',
        path: 'impact',
        component: () => import('#/views/kb/impact/index.vue'),
        meta: {
          icon: 'lucide:git-branch',
          title: '影响分析与代码生成',
        },
      },
      {
        name: 'KbCodeTree',
        path: 'code-tree',
        component: () => import('#/views/kb/code-tree/index.vue'),
        meta: {
          icon: 'lucide:folder-tree',
          title: '代码树与注释',
        },
      },
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
        // 兼容旧入口 /kb/prompts
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
        name: 'KbSystem',
        path: 'system',
        component: () => import('#/views/kb/system/index.vue'),
        meta: {
          icon: 'lucide:settings-2',
          title: '系统状态',
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
