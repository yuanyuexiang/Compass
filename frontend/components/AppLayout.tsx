'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Avatar, Badge, Breadcrumb, Button, Dropdown, Layout, Menu, Space, Tooltip, Typography } from 'antd';
import type { ItemType } from 'antd/es/breadcrumb/Breadcrumb';
import type { MenuProps } from 'antd';
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
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  SearchOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { apiFetch, clearSession, getCachedUser, getToken } from '@/lib/api';
import SelfSettingsModal from '@/components/SelfSettingsModal';
import type { User } from '@/lib/types';

const SIDER_COLLAPSED_KEY = 'compass-sider-collapsed';

// 模块级缓存：AppLayout 随页面切换卸载重建，若每次都从默认值起步再等 effect 读
// localStorage，会闪一次「展开→折叠」。缓存后新实例首帧即是正确状态。
let collapsedCache: boolean | null = null;

const ROLE_LABELS: Record<string, string> = {
  platform_admin: '平台管理员',
  tenant_admin: '企业管理员',
  sales: '成员',
};

const MENU_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: <Link href="/">工作台</Link> },
  { key: '/opportunities', icon: <SearchOutlined />, label: <Link href="/opportunities">商机查询</Link> },
  { key: '/profile', icon: <IdcardOutlined />, label: <Link href="/profile">企业画像</Link> },
  { key: '/settings', icon: <BellOutlined />, label: <Link href="/settings">订阅设置</Link> },
  { key: '/notifications', icon: <MessageOutlined />, label: <Link href="/notifications">通知中心</Link> },
];

const ADMIN_MENU_ITEMS = [
  { key: '/members', icon: <TeamOutlined />, label: <Link href="/members">成员管理</Link> },
];

// 采集源全局共享，增改/启停会影响所有租户 → 采集管理仅平台管理员可见
const PLATFORM_MENU_ITEMS = [
  { key: '/sources', icon: <CloudDownloadOutlined />, label: <Link href="/sources">采集管理</Link> },
  { key: '/models', icon: <ApiOutlined />, label: <Link href="/models">模型服务</Link> },
  { key: '/tenants', icon: <ApartmentOutlined />, label: <Link href="/tenants">租户管理</Link> },
];

const ADMIN_ROLES = ['tenant_admin', 'platform_admin'];

function menuItemsFor(role: string | undefined, collapsed: boolean): MenuProps['items'] {
  const admin = [
    ...(ADMIN_ROLES.includes(role ?? '') ? ADMIN_MENU_ITEMS : []),
    ...(role === 'platform_admin' ? PLATFORM_MENU_ITEMS : []),
  ];
  // 折叠态用扁平列表：antd 只对菜单直接子项做图标居中与悬停提示，嵌在分组里会失效
  if (collapsed) {
    return admin.length
      ? [...MENU_ITEMS, { type: 'divider', style: { borderColor: 'rgba(255,255,255,.12)', margin: '8px 16px' } }, ...admin]
      : [...MENU_ITEMS];
  }
  const items: MenuProps['items'] = [{ type: 'group', label: '工作区', children: MENU_ITEMS }];
  if (admin.length) items.push({ type: 'group', label: '管理', children: admin });
  return items;
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
  // 首屏（缓存为空）与 SSR 一致地从展开态起步，避免水合不一致；页面间切换直接取缓存
  const [collapsed, setCollapsed] = useState(collapsedCache ?? false);
  // 首帧禁用宽度过渡：硬刷新时从 localStorage 同步折叠态是瞬时定位，不播收合动画
  const [animReady, setAnimReady] = useState(false);

  useEffect(() => {
    if (collapsedCache === null) {
      collapsedCache = localStorage.getItem(SIDER_COLLAPSED_KEY) === '1';
      setCollapsed(collapsedCache);
    }
    const timer = setTimeout(() => setAnimReady(true), 80);
    return () => clearTimeout(timer);
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      collapsedCache = !c;
      localStorage.setItem(SIDER_COLLAPSED_KEY, c ? '0' : '1');
      return !c;
    });
  };

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
        width={208}
        collapsedWidth={72}
        collapsible
        collapsed={collapsed}
        trigger={null}
        theme="dark"
        className={`compass-sider${animReady ? '' : ' sider-no-anim'}`}
        style={{ position: 'sticky', top: 0, height: '100vh' }}
      >
        <div className="sider-inner">
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: collapsed ? 'center' : 'flex-start',
              gap: 12,
              padding: collapsed ? '20px 0 16px' : '20px 24px 16px',
            }}
          >
            <CompassOutlined style={{ fontSize: 30, color: '#FAAD14' }} />
            {!collapsed ? (
              <div>
                <div style={{ color: '#fff', fontSize: 20, fontWeight: 600, lineHeight: 1.25 }}>司南</div>
                <div style={{ color: '#8C9BC4', fontSize: 12 }}>AI 寻标 Agent</div>
              </div>
            ) : null}
          </div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[selectedMenuKey(pathname)]}
            items={menuItemsFor(user?.role, collapsed)}
            style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}
          />
          <Tooltip
            title={collapsed ? `${user?.username ?? ''}（${ROLE_LABELS[user?.role ?? ''] ?? ''}）· 点击进入个人设置` : ''}
            placement="right"
          >
            <div
              className="sider-footer"
              style={{ cursor: 'pointer' }}
              onClick={() => setSettingsOpen(true)}
            >
              <Avatar size={30} style={{ background: '#2F54EB', fontSize: 13, flexShrink: 0 }}>
                {avatarChar}
              </Avatar>
              {!collapsed ? (
                <div style={{ minWidth: 0 }}>
                  <div className="sider-footer-name">{user?.username ?? ''}</div>
                  <div className="sider-footer-role">{ROLE_LABELS[user?.role ?? ''] ?? ''}</div>
                </div>
              ) : null}
            </div>
          </Tooltip>
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
            <Button
              type="text"
              aria-label={collapsed ? '展开导航' : '收起导航'}
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={toggleCollapsed}
            />
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
      <SelfSettingsModal
        open={settingsOpen}
        user={user}
        onClose={() => setSettingsOpen(false)}
        onUpdated={onSelfUpdated}
      />
    </Layout>
  );
}
