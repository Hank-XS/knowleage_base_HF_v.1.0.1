import { Modal, message } from 'ant-design-vue';
import { executeCleanup, previewCleanup, type CleanupScope } from '#/api/knowledge-browse';

export async function confirmCleanup(scope: CleanupScope, done: () => Promise<void>) {
  try {
    const preview = await previewCleanup(scope);
    const c = preview.counts;
    if (!(c.chunks + c.vectors + c.nodes + c.edges)) { message.info('所选范围没有可清理的数据'); return; }
    const detail = scope.target === 'chunks'
      ? `删除 ${c.chunks} 个切片，同时移除 ${c.vectors} 条检索索引。源文件、版本正文和图谱结构保留；恢复切片需要重新上传解析。`
      : `删除 ${c.nodes} 个节点和 ${c.edges} 条关联关系，包含当前隐藏的段落、字段。源文件和切片保留，相邻文件的节点保留；恢复图谱需要重新上传解析。`;
    Modal.confirm({ title: `清理${scope.target === 'chunks' ? '切片' : '图谱'}：${preview.title}`,
      content: detail, okText: '确认清理', cancelText: '取消', okType: 'danger',
      async onOk() { await executeCleanup(scope, preview.token); message.success('清理完成'); await done(); },
    });
  } catch (e: any) { message.error(e.response?.data?.message || e.message || '读取清理范围失败'); }
}
