'use client';

import { useCallback, useEffect, useState } from 'react';
import { Alert, App, Avatar, Button, Card, Col, Descriptions, Empty, List, Popconfirm, Row, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CheckOutlined, DeleteOutlined, StopOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import { formatDateTime } from '@/lib/labels';
import type { TenantAdminItem, UsageItem } from '@/lib/types';

const STATUS_COLORS: Record<string, string> = {
  pending: 'orange',
  active: 'green',
  disabled: 'red',
};

const SCENE_LABELS: Record<string, string> = {
  extract: '字段提取',
  match: '匹配精排',
  nl_search: 'AI 搜索',
  profile_suggest: 'AI 画像',
  source_suggest: 'AI 识别数据源',
};

export default function TenantsPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<TenantAdminItem[]>([]);
  const [usage, setUsage] = useState<UsageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ items: TenantAdminItem[] }>('/api/admin/tenants');
      setItems(data.items ?? []);
      setSelectedId((current) => current ?? data.items?.[0]?.id ?? null);
      const u = await apiFetch<{ items: UsageItem[] }>('/api/admin/usage?days=30');
      setUsage(u.items ?? []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (id: number, action: 'approve' | 'enable' | 'disable', label: string) => {
    try {
      await apiFetch(`/api/admin/tenants/${id}/${action}`, { method: 'POST' });
      message.success(`${label}成功`);
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const doDelete = async (rec: TenantAdminItem) => {
    try {
      await apiFetch(`/api/admin/tenants/${rec.id}`, { method: 'DELETE' });
      message.success(`「${rec.name}」已删除（用量账单保留）`);
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const pendingCount = items.filter((t) => t.status === 'pending').length;
  const selected = items.find((item) => String(item.id) === String(selectedId)) ?? null;
  const selectedUsage = usage.filter((item) => String(item.tenant_id) === String(selectedId));

  const columns: ColumnsType<TenantAdminItem> = [
    {
      title: '企业名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, rec) => (
        <Space size={6}>
          <Typography.Text strong>{name}</Typography.Text>
          {rec.is_self ? <Tag>本租户</Tag> : null}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: string, rec) => <Tag color={STATUS_COLORS[s] ?? 'default'}>{rec.status_label}</Tag>,
    },
    {
      title: '管理员',
      key: 'admin',
      width: 220,
      render: (_, rec) => (
        <Space direction="vertical" size={0}>
          <span>{rec.admin_username ?? '-'}</span>
          {rec.admin_email ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {rec.admin_email}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    { title: '成员数', dataIndex: 'user_count', key: 'user_count', width: 80 },
    {
      title: '画像',
      dataIndex: 'has_profile',
      key: 'has_profile',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="blue">已配置</Tag> : <Tag>未配置</Tag>),
    },
    {
      title: '申请时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (v: string | null) => formatDateTime(v),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, rec) => (
        <Space>
          {rec.status === 'pending' ? (
            <Button type="primary" size="small" icon={<CheckOutlined />} onClick={() => act(rec.id, 'approve', '审批')}>
              通过
            </Button>
          ) : null}
          {rec.status === 'disabled' ? (
            <Button size="small" onClick={() => act(rec.id, 'enable', '启用')}>
              启用
            </Button>
          ) : null}
          {rec.status !== 'disabled' && !rec.is_self ? (
            <Popconfirm
              title="停用后该企业所有成员将无法登录，确定？"
              onConfirm={() => act(rec.id, 'disable', '停用')}
            >
              <Button size="small" danger icon={<StopOutlined />}>
                停用
              </Button>
            </Popconfirm>
          ) : null}
          {rec.status !== 'active' && !rec.is_self ? (
            <Popconfirm
              title={`彻底删除「${rec.name}」？`}
              description="将删除该企业的账号、画像、推荐与通知数据，不可恢复（LLM 用量账单保留）"
              okText="删除"
              okButtonProps={{ danger: true }}
              onConfirm={() => doDelete(rec)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          ) : null}
        </Space>
      ),
    },
  ];

  const usageColumns: ColumnsType<UsageItem> = [
    { title: '租户', dataIndex: 'tenant_name', key: 'tenant_name' },
    {
      title: '场景',
      dataIndex: 'scene',
      key: 'scene',
      width: 140,
      render: (s: string) => SCENE_LABELS[s] ?? s,
    },
    { title: '调用次数', dataIndex: 'calls', key: 'calls', width: 100 },
    {
      title: 'Token 总量',
      dataIndex: 'total_tokens',
      key: 'total_tokens',
      width: 120,
      render: (v: number) => v.toLocaleString(),
    },
  ];

  return (
    <AppLayout title="租户管理" subtitle="企业开通审批、启停与 LLM 用量总览（平台管理员）">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {pendingCount > 0 ? (
          <Alert type="warning" showIcon message={`有 ${pendingCount} 个企业开通申请待审批`} />
        ) : null}
        <Row gutter={[16, 16]} align="top">
          <Col xs={24} lg={9} xl={8}>
            <Card className="compass-card opportunity-list-card" title={`租户列表（${items.length}）`}>
              <List<TenantAdminItem>
                loading={loading}
                dataSource={items}
                locale={{ emptyText: <Empty description="暂无租户" /> }}
                renderItem={(item) => (
                  <List.Item className={`opportunity-list-item${String(item.id) === String(selectedId) ? ' opportunity-list-item-active' : ''}`} onClick={() => setSelectedId(item.id)}>
                    <List.Item.Meta
                      avatar={<Avatar shape="square">{item.name.slice(0, 1)}</Avatar>}
                      title={<Space><Typography.Text strong>{item.name}</Typography.Text>{item.is_self ? <Tag>本租户</Tag> : null}</Space>}
                      description={<Space wrap><Tag color={STATUS_COLORS[item.status] ?? 'default'}>{item.status_label}</Tag><Typography.Text type="secondary" style={{ fontSize: 12 }}>{item.user_count} 名成员</Typography.Text></Space>}
                    />
                  </List.Item>
                )}
              />
            </Card>
          </Col>
          <Col xs={24} lg={15} xl={16}>
            <Card className="compass-card opportunity-detail" title={selected?.name ?? '租户详情'}>
              {selected ? <Space direction="vertical" size={20} style={{ width: '100%' }}>
                <Descriptions column={{ xs: 1, md: 2 }}>
                  <Descriptions.Item label="状态"><Tag color={STATUS_COLORS[selected.status] ?? 'default'}>{selected.status_label}</Tag></Descriptions.Item>
                  <Descriptions.Item label="成员数">{selected.user_count}</Descriptions.Item>
                  <Descriptions.Item label="管理员">{selected.admin_username ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="管理员邮箱">{selected.admin_email ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="企业画像">{selected.has_profile ? '已配置' : '未配置'}</Descriptions.Item>
                  <Descriptions.Item label="申请时间">{formatDateTime(selected.created_at)}</Descriptions.Item>
                </Descriptions>
                <Space wrap>
                  {selected.status === 'pending' ? <Button type="primary" icon={<CheckOutlined />} onClick={() => act(selected.id, 'approve', '审批')}>通过申请</Button> : null}
                  {selected.status === 'disabled' ? <Button onClick={() => act(selected.id, 'enable', '启用')}>启用租户</Button> : null}
                  {selected.status !== 'disabled' && !selected.is_self ? <Popconfirm title="停用后该企业所有成员将无法登录，确定？" onConfirm={() => act(selected.id, 'disable', '停用')}><Button danger icon={<StopOutlined />}>停用租户</Button></Popconfirm> : null}
                  {selected.status !== 'active' && !selected.is_self ? <Popconfirm title={`彻底删除「${selected.name}」？`} description="账号、画像、推荐与通知将被删除且不可恢复" okButtonProps={{ danger: true }} onConfirm={() => doDelete(selected)}><Button danger icon={<DeleteOutlined />}>删除租户</Button></Popconfirm> : null}
                </Space>
                <div>
                  <Typography.Text strong>近30天LLM用量</Typography.Text>
                  <Table<UsageItem> style={{ marginTop: 10 }} size="small" rowKey={(r) => `${r.tenant_id}-${r.scene}`} columns={usageColumns.filter((column) => column.key !== 'tenant_name')} dataSource={selectedUsage} loading={loading} pagination={false} locale={{ emptyText: '暂无用量' }} />
                </div>
              </Space> : <Empty description="从左侧选择租户" />}
            </Card>
          </Col>
        </Row>
      </Space>
    </AppLayout>
  );
}
