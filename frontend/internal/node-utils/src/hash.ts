import { createHash } from 'node:crypto';

/**
 * 基于内容生成指纹（SHA-256），可截断长度。
 * 仅用于缓存/资源命名等非安全敏感场景，不用于口令存储。
 * @param content
 * @param hashLSize
 */
function generatorContentHash(content: string, hashLSize?: number) {
  const hash = createHash('sha256').update(content, 'utf8').digest('hex');

  if (hashLSize) {
    return hash.slice(0, hashLSize);
  }

  return hash;
}

export { generatorContentHash };
