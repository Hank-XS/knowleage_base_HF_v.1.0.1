/** 知识库管理页本地演示数据（UI 复刻用） */

export interface KbFolder {
  key: string;
  title: string;
  count: number;
  children?: KbFolder[];
}

export interface KbDoc {
  id: string;
  name: string;
  type: string;
  version: string;
  status: 'draft' | 'review' | 'published';
  vectorized: boolean;
  official: boolean;
  security: 'public' | 'internal' | 'secret' | 'confidential';
  size: string;
  uploadedAt: string;
  kbKey: string;
  path: string;
  content?: string;
  chunks?: KbChunk[];
}

export interface KbChunk {
  id: string;
  title: string;
  text: string;
  start: number;
  end: number;
}

export interface KbVersion {
  version: string;
  content: string;
}

export const KB_FOLDERS: KbFolder[] = [
  {
    key: 'cps',
    title: 'CPS跨境支付',
    count: 128,
    children: [
      { key: 'cps/docs', title: 'docs', count: 36 },
      { key: 'cps/cobol', title: 'cobol', count: 42 },
      { key: 'cps/jcl', title: 'jcl', count: 18 },
      { key: 'cps/mq', title: 'mq', count: 12 },
      { key: 'cps/tickets', title: 'tickets', count: 20 },
    ],
  },
  {
    key: 'atm',
    title: 'ATM取现场景',
    count: 56,
    children: [
      { key: 'atm/docs', title: 'docs', count: 18 },
      { key: 'atm/cobol', title: 'cobol', count: 28 },
      { key: 'atm/mapping', title: 'mapping', count: 10 },
    ],
  },
  { key: 'swift', title: 'SWIFT规则', count: 24 },
  { key: 'recon', title: '日终对账', count: 31 },
  { key: 'demo-test', title: 'demo-test', count: 8 },
];

const PYMAIN_SNIPPET = `       IDENTIFICATION DIVISION.
       PROGRAM-ID. PYMAIN.
      * CPS inbound orchestrator
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TXN-ID            PIC X(20).
       01  WS-RC                PIC S9(4) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 1000-VALIDATE
           PERFORM 2000-AML-CHECK
           PERFORM 3000-ROUTE
           PERFORM 4000-POST
           GOBACK.
`;

const ARCH_MD = `# CPS 跨境支付核心架构

CPS 负责 SWIFT MT/MX 报文收发、清算路由、账务记账与对账。

## 关键路径
1. CGW → MQ CPS.IN.Q
2. CICS PYIN → PYMAIN
3. PYVAL → AML → PYROUTE → PYPOST
4. PYMSGOT 出站
`;

export const KB_DOCS: KbDoc[] = [
  {
    id: 'd1',
    name: 'ARCH-PAY-001_跨境支付核心架构',
    type: 'md',
    version: 'v1.0',
    status: 'draft',
    vectorized: false,
    official: true,
    security: 'public',
    size: '4KB',
    uploadedAt: '2024-10-16 09:12:00',
    kbKey: 'cps',
    path: 'cps/docs',
    content: ARCH_MD,
    chunks: [
      {
        id: 'c1',
        title: '系统定位',
        text: 'CPS 负责 SWIFT MT/MX 报文收发、清算路由、账务记账与对账。',
        start: 0,
        end: 40,
      },
      {
        id: 'c2',
        title: '关键路径',
        text: 'CGW → MQ CPS.IN.Q → CICS PYIN → PYMAIN → PYVAL/AML/PYROUTE/PYPOST → PYMSGOT',
        start: 41,
        end: 120,
      },
    ],
  },
  {
    id: 'd2',
    name: 'PYMAIN',
    type: 'cbl',
    version: 'v3.2.1',
    status: 'published',
    vectorized: true,
    official: true,
    security: 'internal',
    size: '18KB',
    uploadedAt: '2024-10-15 14:22:11',
    kbKey: 'cps',
    path: 'cps/cobol',
    content: PYMAIN_SNIPPET,
    chunks: [
      {
        id: 'c3',
        title: 'MAIN-PARA',
        text: '编排 VALIDATE / AML / ROUTE / POST 四个步骤。',
        start: 200,
        end: 320,
      },
    ],
  },
  {
    id: 'd3',
    name: 'SWIFT_报文处理规则',
    type: 'yaml',
    version: 'v1.4.0',
    status: 'review',
    vectorized: true,
    official: true,
    security: 'public',
    size: '3KB',
    uploadedAt: '2024-10-14 11:03:44',
    kbKey: 'swift',
    path: 'swift',
    content: 'message_types:\n  MT103:\n    mandatory_fields: ["20","23B","32A","50K","59","71A"]\n',
    chunks: [
      {
        id: 'c4',
        title: 'MT103 必填域',
        text: '20 / 23B / 32A / 50K / 59 / 71A',
        start: 0,
        end: 80,
      },
    ],
  },
  {
    id: 'd4',
    name: 'ticket_INC-88355',
    type: 'json',
    version: 'v1.0',
    status: 'published',
    vectorized: true,
    official: false,
    security: 'internal',
    size: '2KB',
    uploadedAt: '2024-09-20 18:10:00',
    kbKey: 'cps',
    path: 'cps/tickets',
    content: '{"ticket_id":"INC-88355","title":"过账死锁导致客户重复借记"}',
  },
  {
    id: 'd5',
    name: 'PYPOST',
    type: 'cbl',
    version: 'v2.1',
    status: 'draft',
    vectorized: false,
    official: true,
    security: 'public',
    size: '7KB',
    uploadedAt: '2024-10-12 16:40:00',
    kbKey: 'cps',
    path: 'cps/cobol',
    content: '       PROGRAM-ID. PYPOST.\n      * fee v1/v2/v3 by CCY\n',
  },
  {
    id: 'd6',
    name: 'atm_withdraw_flow',
    type: 'md',
    version: 'v1.0',
    status: 'published',
    vectorized: true,
    official: true,
    security: 'public',
    size: '5KB',
    uploadedAt: '2024-10-10 10:00:00',
    kbKey: 'atm',
    path: 'atm/docs',
    content: '# ATM 取现流程\n余额检查 → 限额校验 → 记账 → 吐钞',
  },
  {
    id: 'd7',
    name: 'cps_queues',
    type: 'mqsc',
    version: 'v1.0',
    status: 'draft',
    vectorized: false,
    official: true,
    security: 'public',
    size: '4KB',
    uploadedAt: '2024-10-09 09:30:00',
    kbKey: 'cps',
    path: 'cps/mq',
  },
  {
    id: 'd8',
    name: 'PYRECON#',
    type: 'jcl',
    version: 'v1.0',
    status: 'review',
    vectorized: false,
    official: true,
    security: 'internal',
    size: '9KB',
    uploadedAt: '2024-10-08 21:15:00',
    kbKey: 'recon',
    path: 'recon',
  },
  {
    id: 'd9',
    name: 'README',
    type: 'md',
    version: 'v1.0',
    status: 'draft',
    vectorized: false,
    official: true,
    security: 'public',
    size: '1KB',
    uploadedAt: '2024-10-07 08:00:00',
    kbKey: 'demo-test',
    path: 'demo-test',
    content: '# demo dataset',
  },
  {
    id: 'd10',
    name: 'mapping_atm_withdraw',
    type: 'csv',
    version: 'v1.0',
    status: 'published',
    vectorized: true,
    official: true,
    security: 'public',
    size: '2KB',
    uploadedAt: '2024-10-06 12:00:00',
    kbKey: 'atm',
    path: 'atm/mapping',
  },
];

export const DOC_VERSIONS: Record<string, KbVersion[]> = {
  d1: [
    {
      version: 'v1.0',
      content: ARCH_MD,
    },
    {
      version: 'v1.1',
      content: `${ARCH_MD}\n\n## 非功能指标\n联机峰值 TPS 850，P99 ≤ 800ms。\n`,
    },
  ],
  d2: [
    { version: 'v3.2.0', content: PYMAIN_SNIPPET.replace('v3.2.1', 'v3.2.0') },
    {
      version: 'v3.2.1',
      content: `${PYMAIN_SNIPPET}\n      * CHG-2024-10442 NOSTRO check\n`,
    },
  ],
};

export const CODE_FILES = [
  {
    key: 'PYMAIN.cbl',
    label: 'PYMAIN.cbl',
    version: 'v3.2.1',
    kb: 'cps',
    content: PYMAIN_SNIPPET,
    relatedDocs: [
      {
        id: 'd1',
        name: 'ARCH-PAY-001_跨境支付核心架构.md',
        section: '关键路径 · PYMAIN 编排',
      },
    ],
  },
  {
    key: 'PYPOST.cbl',
    label: 'PYPOST.cbl',
    version: 'v2.1',
    kb: 'cps',
    content:
      '       PROGRAM-ID. PYPOST.\n       PROCEDURE DIVISION.\n           PERFORM FEE-CALC\n           PERFORM DB2-UPDATE.\n',
    relatedDocs: [
      {
        id: 'd4',
        name: 'ticket_INC-88355.json',
        section: '死锁重试与幂等',
      },
    ],
  },
  {
    key: 'DocumentResource.java',
    label: 'DocumentResource.java',
    version: 'v1.0',
    kb: 'demo-test',
    content: `package com.example.kb.facade;

import com.example.kb.error.BusinessException;
import com.example.kb.service.DocumentService;

public class DocumentResource {
    private final DocumentService documentService;

    public DocumentResource(DocumentService documentService) {
        this.documentService = documentService;
    }
}
`,
    relatedDocs: [] as { id: string; name: string; section: string }[],
  },
];

export const VERSION_OPTIONS = ['v1.0', 'v1.1', 'v2.0', 'v2.1', 'v3.2.0', 'v3.2.1'];

export const CHIP_TAGS = [
  'SWIFT',
  'MT103',
  'CNAPS',
  'AML',
  'Nostro',
  'CICS',
  'MQ',
  '对账',
];

export function statusLabel(s: KbDoc['status']) {
  return { draft: '草稿', review: '审核中', published: '已发布' }[s];
}

export function securityLabel(s: KbDoc['security']) {
  return {
    public: '公开',
    internal: '内部',
    secret: '秘密',
    confidential: '机密',
  }[s];
}
