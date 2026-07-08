'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Avatar, Badge, Breadcrumb, Button, Layout, Menu, Space, Typography } from 'antd';
import type { ItemType } from 'antd/es/breadcrumb/Breadcrumb';
import {
  BellOutlined,
  CloudDownloadOutlined,
  CompassOutlined,
  DashboardOutlined,
  HomeOutlined,
  IdcardOutlined,
  LogoutOutlined,
  MessageOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { apiFetch, clearSession, getCachedUser, getToken } from '@/lib/api';
import type { User } from '@/lib/types';

const MENU_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: <Link href="/">工作台</Link> },
  { key: '/opportunities', icon: <SearchOutlined />, label: <Link href="/opportunities">商机查询</Link> },
  { key: '/profile', icon: <IdcardOutlined />, label: <Link href="/profile">企业画像</Link> },
  { key: '/settings', icon: <BellOutlined />, label: <Link href="/settings">订阅设置</Link> },
  { key: '/notifications', icon: <MessageOutlined />, label: <Link href="/notifications">通知中心</Link> },
];

const ADMIN_MENU_ITEMS = [
  { key: '/sources', icon: <CloudDownloadOutlined />, label: <Link href="/sources">采集管理</Link> },
];

const ADMIN_ROLES = ['tenant_admin', 'platform_admin'];

function menuItemsFor(role: string | undefined) {
  return ADMIN_ROLES.includes(role ?? '') ? [...MENU_ITEMS, ...ADMIN_MENU_ITEMS] : MENU_ITEMS;
}

function selectedMenuKey(pathname: string): string {
  if (pathname === '/') return '/';
  if (pathname.startsWith('/projects')) return '/opportunities';
  const hit = [...MENU_ITEMS, ...ADMIN_MENU_ITEMS]
    .map((i) => i.key)
    .filter((k) => k !== '/')
    .find((k) => pathname.startsWith(k));
  return hit ?? '/';
}

const PAGE_LABELS: Record<string, string> = {
  '/opportunities': '商机查询',
  '/profile': '企业画像',
  '/settings': '订阅设置',
  '/notifications': '通知中心',
  '/sources': '采集管理',
};

/** 顶栏面包屑：首页可点击回工作台；项目详情显示三级路径。 */
function breadcrumbItems(pathname: string): ItemType[] {
  const home: ItemType = {
    title: (
      <Link href="/">
        <HomeOutlined /> 首页
      </Link>
    ),
  };
  if (pathname === '/') {
    return [{ title: (<><HomeOutlined /> 工作台</>) }];
  }
  if (pathname.startsWith('/projects')) {
    return [
      home,
      { title: <Link href="/opportunities">商机查询</Link> },
      { title: '项目详情' },
    ];
  }
  const key = Object.keys(PAGE_LABELS).find((k) => pathname.startsWith(k));
  return [home, { title: key ? PAGE_LABELS[key] : '' }];
}

interface AppLayoutProps {
  children: ReactNode;
  title?: string;
  subtitle?: string;
}

export default function AppLayout({ children, title, subtitle }: AppLayoutProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [unread, setUnread] = useState(0);

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
    apiFetch<{ tenant?: { unread: number } }>('/api/stats')
      .then((s) => setUnread(s.tenant?.unread ?? 0))
      .catch(() => {});
  }, [router, pathname]);

  const logout = () => {
    clearSession();
    router.replace('/login');
  };

  const avatarChar = (user?.username ?? '?').slice(0, 1).toUpperCase();

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider width={208} theme="dark" className="compass-sider">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '20px 20px 16px',
          }}
        >
          <CompassOutlined style={{ fontSize: 30, color: '#FAAD14' }} />
          <div>
            <div style={{ color: '#fff', fontSize: 20, fontWeight: 600, lineHeight: 1.25 }}>司南</div>
            <div style={{ color: '#8C9BC4', fontSize: 12 }}>AI 寻标 Agent</div>
          </div>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedMenuKey(pathname)]}
          items={menuItemsFor(user?.role)}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #F0F0F0',
            height: 56,
            lineHeight: '56px',
          }}
        >
          <Breadcrumb items={breadcrumbItems(pathname)} style={{ fontSize: 14 }} />
          <Space size="middle">
            <Badge count={unread} size="small" offset={[-2, 4]}>
              <Button
                type="text"
                aria-label="通知中心"
                icon={<BellOutlined style={{ fontSize: 17 }} />}
                onClick={() => router.push('/notifications')}
              />
            </Badge>
            <Space size={8}>
              <Avatar size={32} style={{ background: '#2F54EB', fontSize: 14 }}>
                {avatarChar}
              </Avatar>
              <Typography.Text strong>{user?.tenant_name ?? ''}</Typography.Text>
              <Typography.Text type="secondary">{user?.username ?? ''}</Typography.Text>
            </Space>
            <Button icon={<LogoutOutlined />} onClick={logout}>
              退出
            </Button>
          </Space>
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          {title ? (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 20, fontWeight: 600, color: 'rgba(0, 0, 0, 0.88)' }}>{title}</div>
              {subtitle ? (
                <div style={{ fontSize: 13, color: 'rgba(0, 0, 0, 0.45)', marginTop: 4 }}>{subtitle}</div>
              ) : null}
            </div>
          ) : null}
          {children}
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
