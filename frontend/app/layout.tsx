import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { AntdRegistry } from '@ant-design/nextjs-registry';
import Providers from './providers';
import './globals.css';

export const metadata: Metadata = {
  title: '司南 · AI 寻标 Agent',
  description: 'Project Compass —— 招投标商机智能推荐平台',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AntdRegistry>
          <Providers>{children}</Providers>
        </AntdRegistry>
      </body>
    </html>
  );
}
