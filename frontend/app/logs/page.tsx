'use client';

import { useCallback, useEffect, useState } from 'react';
import { Alert, Card, Input, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import AppLayout from '@/components/AppLayout';
import { apiFetch, getCachedUser } from '@/lib/api';
import { formatDateTime } from '@/lib/labels';
import type { AuditLogItem, SystemEventItem, User } from '@/lib/types';

const PAGE_SIZE = 50;

/** 动作键 → 中文（未收录的键原样展示，后端新增埋点无需同步改前端） */
const ACTION_LABELS: Record<string, string> = {
  'auth.register': '注册申请',
  'auth.login': '登录',
  'auth.login_failed': '登录失败',
  'me.update': '修改个人信息',
  'me.password_change': '修改密码',
  'user.create': '新增成员',
  'user.update': '修改成员',
  'user.password_reset': '重置成员密码',
  'follow.update': '商机跟进',
  'profile.save': '保存画像',
  'subscription.save': '保存订阅',
  'material.upload': '上传材料',
  'material.delete': '删除材料',
  'fact.confirm': '确认案例',
  'fact.reject': '驳回案例',
  'source.request': '申请数据源',
  'source.approve': '审批数据源',
  'source.reject': '驳回数据源',
  'source.create': '新建数据源',
  'source.update': '修改数据源',
  'source.delete': '删除数据源',
  'source.schedule': '调整采集间隔',
  'source.crawl': '手动采集',
  'source.crawl_all': '手动全量采集',
  'tenant.approve': '审批租户',
  'tenant.enable': '启用租户',
  'tenant.disable': '停用租户',
  'tenant.delete': '删除租户',
  'llm.config_save': '保存模型配置',
};

const ACTION_GROUPS = [
  { value: '', label: '全部动作' },
  { value: 'auth.', label: '登录与注册' },
  { value: 'user.', label: '成员管理' },
  { value: 'profile.', label: '企业画像' },
  { value: 'source.', label: '数据源' },
  { value: 'tenant.', label: '租户管理' },
  { value: 'llm.', label: '模型服务' },
];

const EVENT_LABELS: Record<string, string> = {
  'crawl.round': '采集轮次',
  'backpressure.pause': '背压暂停',
  'clean.failure': '清洗失败',
  'extract.skip_stale': '放弃过期公告',
  'pipeline.sweep': '流水线补偿',
  'llm.probe': 'LLM 探针模式',
  'llm.fallback': '备用模型切换',
  'profile.rematch': '画像重评估',
  'health.alert': '健康告警',
};

const LEVEL_COLORS: Record<string, string> = { info: 'blue', warning: 'orange', error: 'red' };
const LEVEL_LABELS: Record<string, string> = { info: '信息', warning: '警告', error: '错误' };

function detailText(detail: Record<string, unknown> | null): string | null {
  if (!detail || Object.keys(detail).length === 0) return null;
  return JSON.stringify(detail, null, 2);
}

function AuditTab({ isPlatform }: { isPlatform: boolean }) {
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState('');
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String((page - 1) * PAGE_SIZE),
      });
      if (action) params.set('action', action);
      if (isPlatform && q.trim()) params.set('q', q.trim());
      const base = isPlatform ? '/api/admin/audit-logs' : '/api/tenant/audit-logs';
      const data = await apiFetch<{ items: AuditLogItem[]; total: number }>(`${base}?${params}`);
      setItems(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [isPlatform, page, action, q]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Space wrap>
        <Select
          value={action}
          style={{ width: 160 }}
          options={ACTION_GROUPS}
          onChange={(v) => {
            setPage(1);
            setAction(v);
          }}
        />
        {isPlatform ? (
          <Input.Search
            placeholder="按操作者/对象搜索"
            allowClear
            style={{ width: 240 }}
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
          />
        ) : null}
      </Space>
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Table<AuditLogItem>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={items}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`,
          onChange: setPage,
        }}
        expandable={{
          rowExpandable: (r) => Boolean(detailText(r.detail)),
          expandedRowRender: (r) => (
            <pre style={{ margin: 0, fontSize: 12 }}>{detailText(r.detail)}</pre>
          ),
        }}
        columns={[
          {
            title: '时间',
            dataIndex: 'created_at',
            width: 170,
            render: (v: string | null) => formatDateTime(v),
          },
          {
            title: '操作者',
            dataIndex: 'username',
            width: 140,
            render: (v: string | null) => v ?? '-',
          },
          {
            title: '动作',
            dataIndex: 'action',
            width: 140,
            render: (v: string) => <Tag>{ACTION_LABELS[v] ?? v}</Tag>,
          },
          {
            title: '对象',
            dataIndex: 'target',
            ellipsis: true,
            render: (v: string | null) => v ?? '-',
          },
          ...(isPlatform
            ? [
                {
                  title: 'IP',
                  dataIndex: 'ip' as const,
                  width: 130,
                  render: (v: string | null) => v ?? '-',
                },
              ]
            : []),
        ]}
      />
    </Space>
  );
}

function SystemTab() {
  const [items, setItems] = useState<SystemEventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [level, setLevel] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String((page - 1) * PAGE_SIZE),
      });
      if (level) params.set('level', level);
      const data = await apiFetch<{ items: SystemEventItem[]; total: number }>(
        `/api/admin/system-events?${params}`,
      );
      setItems(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [page, level]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Select
        value={level}
        style={{ width: 140 }}
        options={[
          { value: '', label: '全部级别' },
          { value: 'info', label: '信息' },
          { value: 'warning', label: '警告' },
          { value: 'error', label: '错误' },
        ]}
        onChange={(v) => {
          setPage(1);
          setLevel(v);
        }}
      />
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Table<SystemEventItem>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={items}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`,
          onChange: setPage,
        }}
        columns={[
          {
            title: '时间',
            dataIndex: 'created_at',
            width: 170,
            render: (v: string | null) => formatDateTime(v),
          },
          {
            title: '级别',
            dataIndex: 'level',
            width: 90,
            render: (v: string) => <Tag color={LEVEL_COLORS[v]}>{LEVEL_LABELS[v] ?? v}</Tag>,
          },
          {
            title: '事件',
            dataIndex: 'event',
            width: 140,
            render: (v: string) => EVENT_LABELS[v] ?? v,
          },
          {
            title: '内容',
            dataIndex: 'message',
            render: (v: string) => (
              <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>{v}</Typography.Text>
            ),
          },
        ]}
      />
    </Space>
  );
}

export default function LogsPage() {
  const me = getCachedUser<User>();
  const isPlatform = me?.role === 'platform_admin';

  return (
    <AppLayout
      title="日志"
      subtitle={isPlatform ? '全平台操作日志与系统运行日志' : '本企业成员的操作记录'}
    >
      <Card className="compass-card">
        {isPlatform ? (
          <Tabs
            items={[
              { key: 'audit', label: '操作日志', children: <AuditTab isPlatform /> },
              { key: 'system', label: '运行日志', children: <SystemTab /> },
            ]}
          />
        ) : (
          <AuditTab isPlatform={false} />
        )}
      </Card>
    </AppLayout>
  );
}
