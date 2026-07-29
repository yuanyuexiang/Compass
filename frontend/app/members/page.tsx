'use client';

import { useCallback, useEffect, useState } from 'react';
import { Alert, App, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
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
  const [createForm] = Form.useForm<CreateForm>();
  const [resetForm] = Form.useForm<{ password: string }>();
  const me = getCachedUser<User>();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ items: MemberItem[] }>('/api/tenant/users');
      setItems(data.items ?? []);
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

  const columns: ColumnsType<MemberItem> = [
    {
      title: '用户名',
      dataIndex: 'username',
      key: 'username',
      render: (v: string, rec) => (
        <Space size={6}>
          <span style={{ fontWeight: 500 }}>{v}</span>
          {String(rec.id) === String(me?.id) ? <Tag>我</Tag> : null}
        </Space>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 130,
      render: (r: string, rec) =>
        r === 'platform_admin' ? (
          <Tag color="gold">{rec.role_label}</Tag>
        ) : r === 'tenant_admin' ? (
          <Tag color="geekblue">{rec.role_label}</Tag>
        ) : (
          <Tag>{rec.role_label}</Tag>
        ),
    },
    { title: '邮箱', dataIndex: 'email', key: 'email', width: 200, render: (v: string | null) => v ?? '-' },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="green">正常</Tag> : <Tag color="red">已停用</Tag>),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (v: string | null) => formatDateTime(v),
    },
    {
      title: '操作',
      key: 'actions',
      width: 300,
      render: (_, rec) => {
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
      },
    },
  ];

  return (
    <AppLayout title="成员管理" subtitle="管理本企业的登录账号与角色">
      <Card
        className="compass-card"
        title="成员列表"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新增成员
          </Button>
        }
      >
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        <Table<MemberItem>
          size="middle"
          rowKey={(r) => String(r.id)}
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={false}
        />
      </Card>

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
