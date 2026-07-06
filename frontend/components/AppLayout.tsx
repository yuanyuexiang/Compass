'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Button, Layout, Menu, Space, Typography } from 'antd';
import {
  BellOutlined,
  CompassOutlined,
  DashboardOutlined,
  IdcardOutlined,
  LogoutOutlined,
  SearchOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { apiFetch, clearSession, getCachedUser, getToken } from '@/lib/api';
import type { User } from '@/lib/types';

const MENU_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: <Link href="/">工作台</Link> },
  { key: '/opportunities', icon: <SearchOutlined />, label: <Link href="/opportunities">商机查询</Link> },
  { key: '/profile', icon: <IdcardOutlined />, label: <Link href="/profile">企业画像</Link> },
  { key: '/settings', icon: <SettingOutlined />, label: <Link href="/settings">订阅设置</Link> },
  { key: '/notifications', icon: <BellOutlined />, label: <Link href="/notifications">通知</Link> },
];

function selectedMenuKey(pathname: string): string {
  if (pathname === '/') return '/';
  if (pathname.startsWith('/projects')) return '/opportunities';
  const hit = MENU_ITEMS.map((i) => i.key)
    .filter((k) => k !== '/')
    .find((k) => pathname.startsWith(k));
  return hit ?? '/';
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
      return;
    }
    const cached = getCachedUser<User>();
    if (cached) setUser(cached);
    apiFetch<User>('/api/me')
      .then((me) => {
        setUser(me);
        localStorage.setItem('user', JSON.stringify(me));
      })
      .catch(() => {
        // 后端未启动时使用缓存信息，静默降级
      });
  }, [router]);

  const logout = () => {
    clearSession();
    router.replace('/login');
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider width={208} theme="dark">
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 16,
            fontWeight: 600,
          }}
        >
          <CompassOutlined style={{ marginRight: 8 }} />
          司南 · 寻标 Agent
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selectedMenuKey(pathname)]} items={MENU_ITEMS} />
      </Layout.Sider>
      <Layout>
        <Layout.Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Space size="middle">
            {user?.tenant_name ? <Typography.Text strong>{user.tenant_name}</Typography.Text> : null}
            {user?.username ? <Typography.Text type="secondary">{user.username}</Typography.Text> : null}
            <Button icon={<LogoutOutlined />} onClick={logout}>
              退出
            </Button>
          </Space>
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>{children}</Layout.Content>
      </Layout>
    </Layout>
  );
}
