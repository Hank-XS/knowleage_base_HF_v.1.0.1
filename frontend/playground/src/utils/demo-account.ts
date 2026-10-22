import type { Recordable } from '@vben/types';

/**
 * Playground 演示账号密码从环境变量读取，避免源码硬编码凭证。
 * 本地开发在 .env.local 中设置：VITE_DEMO_PASSWORD=<mock-password>
 */
export function getDemoPassword(): string {
  const password = import.meta.env.VITE_DEMO_PASSWORD;
  if (!password || typeof password !== 'string') {
    throw new Error(
      '缺少 VITE_DEMO_PASSWORD：请在 playground/.env.local 中配置演示账号密码',
    );
  }
  return password;
}

export function getDemoAccounts(): Record<string, Recordable<any>> {
  const password = getDemoPassword();
  return {
    admin: {
      password,
      username: 'admin',
    },
    super: {
      password,
      username: 'vben',
    },
    user: {
      password,
      username: 'jack',
    },
  };
}
