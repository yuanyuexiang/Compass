'use client';

import '@ant-design/v5-patch-for-react-19';
import type { ReactNode } from 'react';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';

dayjs.locale('zh-cn');

export default function Providers({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider locale={zhCN}>
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}
