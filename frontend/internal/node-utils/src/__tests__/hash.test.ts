import { createHash } from 'node:crypto';

import { describe, expect, it } from 'vitest';

import { generatorContentHash } from '../hash';

function sha256Hex(content: string) {
  return createHash('sha256').update(content, 'utf8').digest('hex');
}

describe('generatorContentHash', () => {
  it('should generate a SHA-256 hash for the content', () => {
    const content = 'example content';
    const expectedHash = sha256Hex(content);
    const actualHash = generatorContentHash(content);
    expect(actualHash).toBe(expectedHash);
  });

  it('should generate a hash with specified length', () => {
    const content = 'example content';
    const hashLength = 10;
    const generatedHash = generatorContentHash(content, hashLength);
    expect(generatedHash).toHaveLength(hashLength);
  });

  it('should correctly generate the hash with specified length', () => {
    const content = 'example content';
    const hashLength = 8;
    const expectedHash = sha256Hex(content).slice(0, hashLength);
    const generatedHash = generatorContentHash(content, hashLength);
    expect(generatedHash).toBe(expectedHash);
  });

  it('should return full hash if hash length parameter is not provided', () => {
    const content = 'example content';
    const expectedHash = sha256Hex(content);
    const actualHash = generatorContentHash(content);
    expect(actualHash).toBe(expectedHash);
  });

  it('should handle empty content', () => {
    const content = '';
    const expectedHash = sha256Hex(content);
    const actualHash = generatorContentHash(content);
    expect(actualHash).toBe(expectedHash);
  });
});
