'use client';

import { useCallback, useEffect, useState } from 'react';
import { Alert, App, Avatar, Button, Card, Col, Descriptions, Empty, Form, Input, List, Modal, Popconfirm, Row, Select, Space, Tag, Typography } from 'antd';
import { KeyOutlined, PlusOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch, getCachedUser } from '@/lib/api';
import { formatDateTime } from '@/lib/labels';
import type { MemberItem, User } from '@/lib/types';

const PASSWORD_RULE = {
  pattern: /^(?=.*[A-Za-z])(?=.*\d).{8,}$/,
  message: '至少 8 位，需同时包含字母和数字',
};

interface CreateForm {
  username: string;
  password: string;
  email?: string;
  role: string;
}

export default function MembersPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<MemberItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState<MemberItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState<number | string | null>(null);
  const [createForm] = Form.useForm<CreateForm>();
  const [resetForm] = Form.useForm<{ password: string }>();
  const me = getCachedUser<User>();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ items: MemberItem[] }>('/api/tenant/users');
      setItems(data.items ?? []);
      setSelectedId((current) => current ?? data.items?.[0]?.id ?? null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const doCreate = async (values: CreateForm) => {
    setSaving(true);
    try {
      await apiFetch('/api/tenant/users', {
        method: 'POST',
        body: JSON.stringify({
          ...values,
          username: values.username.trim(),
          email: values.email || null,
        }),
      });
      message.success('成员已添加');
      setCreateOpen(false);
      createForm.resetFields();
      load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const patch = async (id: number, body: Record<string, unknown>, label: string) => {
    try {
      await apiFetch(`/api/tenant/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
      message.success(`${label}成功`);
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const doReset = async (values: { password: string }) => {
    if (!resetTarget) return;
    setSaving(true);
    try {
      await apiFetch(`/api/tenant/users/${resetTarget.id}/reset-password`, {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success(`已重置 ${resetTarget.username} 的密码`);
      setResetTarget(null);
      resetForm.resetFields();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const memberActions = (rec: MemberItem) => {
        const isSelf = String(rec.id) === String(me?.id);
        const isPlatformAdmin = rec.role === 'platform_admin';
        return (
          <Space wrap>
            <Button size="small" icon={<KeyOutlined />} onClick={() => setResetTarget(rec)} disabled={isPlatformAdmin && !isSelf && me?.role !== 'platform_admin'}>
              重置密码
            </Button>
            {!isSelf && !isPlatformAdmin ? (
              <>
                {rec.role === 'sales' ? (
                  <Button size="small" onClick={() => patch(rec.id, { role: 'tenant_admin' }, '设为企业管理员')}>
                    设为管理员
                  </Button>
                ) : (
                  <Button size="small" onClick={() => patch(rec.id, { role: 'sales' }, '设为业务员')}>
                    设为业务员
                  </Button>
                )}
                {rec.enabled ? (
                  <Popconfirm title="停用后该成员将无法登录，确定？" onConfirm={() => patch(rec.id, { enabled: false }, '停用')}>
                    <Button size="small" danger>
                      停用
                    </Button>
                  </Popconfirm>
                ) : (
                  <Button size="small" onClick={() => patch(rec.id, { enabled: true }, '启用')}>
                    启用
                  </Button>
                )}
              </>
            ) : null}
          </Space>
        );
  };

  const selected = items.find((item) => String(item.id) === String(selectedId)) ?? null;

  return (
    <AppLayout title="成员管理" subtitle="管理本企业的登录账号与角色">
      <Row gutter={[16, 16]} align="top">
        <Col xs={24} lg={9} xl={8}>
      <Card className="compass-card opportunity-list-card" title="成员列表" extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新增</Button>}>
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        <List<MemberItem>
          loading={loading}
          dataSource={items}
          locale={{ emptyText: <Empty description="暂无成员" /> }}
          renderItem={(item) => (
            <List.Item className={`opportunity-list-item${String(item.id) === String(selectedId) ? ' opportunity-list-item-active' : ''}`} onClick={() => setSelectedId(item.id)}>
              <List.Item.Meta
                avatar={<Avatar>{item.username.slice(0, 1).toUpperCase()}</Avatar>}
                title={<Space><Typography.Text strong>{item.username}</Typography.Text>{String(item.id) === String(me?.id) ? <Tag>我</Tag> : null}</Space>}
                description={<Space wrap><Tag color={item.role === 'platform_admin' ? 'gold' : item.role === 'tenant_admin' ? 'geekblue' : 'default'}>{item.role_label}</Tag><Tag color={item.enabled ? 'green' : 'red'}>{item.enabled ? '正常' : '已停用'}</Tag></Space>}
              />
            </List.Item>
          )}
        />
      </Card>
        </Col>
        <Col xs={24} lg={15} xl={16}>
          <Card className="compass-card opportunity-detail" title={selected?.username ?? '成员详情'}>
            {selected ? <Space direction="vertical" size={20} style={{ width: '100%' }}>
              <Descriptions column={{ xs: 1, md: 2 }}>
                <Descriptions.Item label="用户名">{selected.username}</Descriptions.Item>
                <Descriptions.Item label="角色">{selected.role_label}</Descriptions.Item>
                <Descriptions.Item label="邮箱">{selected.email ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="状态">{selected.enabled ? '正常' : '已停用'}</Descriptions.Item>
                <Descriptions.Item label="创建时间">{formatDateTime(selected.created_at)}</Descriptions.Item>
              </Descriptions>
              <div><Typography.Text strong>账号操作</Typography.Text><div style={{ marginTop: 12 }}>{memberActions(selected)}</div></div>
            </Space> : <Empty description="从左侧选择成员" />}
          </Card>
        </Col>
      </Row>

      <Modal
        title="新增成员"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={saving}
        okText="添加"
        destroyOnHidden
      >
        <Form<CreateForm> form={createForm} layout="vertical" onFinish={doCreate} initialValues={{ role: 'sales' }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }, { min: 2, message: '至少 2 个字符' }]}>
            <Input placeholder="登录用户名" />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, message: '请输入初始密码' }, PASSWORD_RULE]}>
            <Input.Password placeholder="至少 8 位，含字母和数字" />
          </Form.Item>
          <Form.Item name="email" label="邮箱（选填）" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
            <Input placeholder="用于接收通知" />
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Select
              options={[
                { value: 'sales', label: '业务员' },
                { value: 'tenant_admin', label: '企业管理员' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={resetTarget ? `重置密码：${resetTarget.username}` : '重置密码'}
        open={resetTarget !== null}
        onCancel={() => setResetTarget(null)}
        onOk={() => resetForm.submit()}
        confirmLoading={saving}
        okText="重置"
        destroyOnHidden
      >
        <Form form={resetForm} layout="vertical" onFinish={doReset}>
          <Form.Item name="password" label="新密码" rules={[{ required: true, message: '请输入新密码' }, PASSWORD_RULE]}>
            <Input.Password placeholder="至少 8 位，含字母和数字" />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  );
}
