'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Avatar, Badge, Breadcrumb, Button, Dropdown, Layout, Space, Typography } from 'antd';
import type { ItemType } from 'antd/es/breadcrumb/Breadcrumb';
import {
  ApartmentOutlined,
  ApiOutlined,
  BellOutlined,
  CloudDownloadOutlined,
  CompassOutlined,
  DashboardOutlined,
  HomeOutlined,
  IdcardOutlined,
  LogoutOutlined,
  MessageOutlined,
  SearchOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { apiFetch, clearSession, getCachedUser, getToken } from '@/lib/api';
import SelfSettingsModal from '@/components/SelfSettingsModal';
import type { User } from '@/lib/types';

const MENU_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: '工作台' },
  { key: '/opportunities', icon: <SearchOutlined />, label: '商机' },
  { key: '/profile', icon: <IdcardOutlined />, label: '画像' },
  { key: '/settings', icon: <BellOutlined />, label: '订阅' },
  { key: '/notifications', icon: <MessageOutlined />, label: '通知' },
];

const ADMIN_MENU_ITEMS = [
  { key: '/members', icon: <TeamOutlined />, label: '成员' },
];

// 采集源全局共享，增改/启停会影响所有租户 → 采集管理仅平台管理员可见
const PLATFORM_MENU_ITEMS = [
  { key: '/sources', icon: <CloudDownloadOutlined />, label: '采集' },
  { key: '/models', icon: <ApiOutlined />, label: '模型' },
  { key: '/tenants', icon: <ApartmentOutlined />, label: '租户' },
];

const ADMIN_ROLES = ['tenant_admin', 'platform_admin'];

function menuItemsFor(role: string | undefined) {
  return [
    ...MENU_ITEMS,
    ...(ADMIN_ROLES.includes(role ?? '') ? ADMIN_MENU_ITEMS : []),
    ...(role === 'platform_admin' ? PLATFORM_MENU_ITEMS : []),
  ];
}

function selectedMenuKey(pathname: string): string {
  if (pathname === '/') return '/';
  if (pathname.startsWith('/projects')) return '/opportunities';
  const hit = [...MENU_ITEMS, ...ADMIN_MENU_ITEMS, ...PLATFORM_MENU_ITEMS]
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
  '/members': '成员管理',
  '/sources': '采集管理',
  '/models': '模型服务',
  '/tenants': '租户管理',
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

  const [settingsOpen, setSettingsOpen] = useState(false);

  const onSelfUpdated = (u: User) => {
    setUser(u);
    localStorage.setItem('user', JSON.stringify(u));
  };

  const userMenu = {
    items: [
      { key: 'settings', icon: <SettingOutlined />, label: '个人设置' },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'settings') setSettingsOpen(true);
      if (key === 'logout') logout();
    },
  };

  const avatarChar = (user?.username ?? '?').slice(0, 1).toUpperCase();

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        width={84}
        theme="dark"
        className="compass-sider"
        style={{ position: 'sticky', top: 0, height: '100vh' }}
      >
        <div className="sider-inner">
          <div className="rail-brand" aria-label="司南 AI 寻标 Agent">
            <div className="rail-brand-ring"><CompassOutlined /><span>南</span></div>
          </div>
          <nav className="rail-nav" aria-label="主导航">
            {menuItemsFor(user?.role).map((item) => {
              const selected = selectedMenuKey(pathname) === item.key;
              const icon = item.key === '/notifications' ? (
                <Badge count={unread} size="small" offset={[5, -2]}>{item.icon}</Badge>
              ) : item.icon;
              return (
                <Link key={item.key} href={item.key} className={`rail-item${selected ? ' rail-item-active' : ''}`}>
                  <span className="rail-item-icon">{icon}</span>
                  <span className="rail-item-label">{item.label}</span>
                </Link>
              );
            })}
          </nav>
          <div className="rail-actions">
            <button type="button" className="rail-item rail-button" onClick={() => setSettingsOpen(true)}>
              <span className="rail-user-avatar">{avatarChar}</span>
              <span className="rail-item-label">个人</span>
            </button>
            <button type="button" className="rail-item rail-button" onClick={logout}>
              <span className="rail-item-icon"><LogoutOutlined /></span>
              <span className="rail-item-label">退出</span>
            </button>
          </div>
        </div>
      </Layout.Sider>
      <Layout>
        <Layout.Header
          className="compass-header"
          style={{
            background: '#fff',
            padding: '0 16px 0 8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #F0F0F0',
            height: 56,
            lineHeight: '56px',
            position: 'sticky',
            top: 0,
            zIndex: 10,
          }}
        >
          <Space size={4}>
            <Breadcrumb items={breadcrumbItems(pathname)} style={{ fontSize: 14 }} />
          </Space>
          <Space size="middle">
            <Badge count={unread} size="small" offset={[-2, 4]}>
              <Button
                type="text"
                aria-label="通知中心"
                icon={<BellOutlined style={{ fontSize: 17 }} />}
                onClick={() => router.push('/notifications')}
              />
            </Badge>
            <Dropdown menu={userMenu} trigger={['click']}>
              <Space size={8} style={{ cursor: 'pointer' }}>
                <Avatar size={32} style={{ background: '#2F54EB', fontSize: 14 }}>
                  {avatarChar}
                </Avatar>
                <Typography.Text strong>{user?.tenant_name ?? ''}</Typography.Text>
                <Typography.Text type="secondary">{user?.username ?? ''}</Typography.Text>
              </Space>
            </Dropdown>
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
      <SelfSettingsModal
        open={settingsOpen}
        user={user}
        onClose={() => setSettingsOpen(false)}
        onUpdated={onSelfUpdated}
      />
    </Layout>
  );
}
