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
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#2F54EB',
          colorSuccess: '#52C41A',
          colorWarning: '#FAAD14',
          colorError: '#F5222D',
          borderRadius: 10,
          fontSize: 14,
          colorBgLayout: '#F5F7FA',
        },
      }}
    >
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}
