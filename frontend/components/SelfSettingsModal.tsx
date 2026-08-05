'use client';

import { useEffect, useState } from 'react';
import { App, Form, Input, Modal } from 'antd';
import { LockOutlined, MailOutlined, PhoneOutlined } from '@ant-design/icons';
import { apiFetch } from '@/lib/api';
import type { User } from '@/lib/types';

interface Props {
  open: boolean;
  user: User | null;
  onClose: () => void;
  /** 邮箱等资料更新成功后回传最新用户信息（用于刷新顶栏/侧栏展示与本地缓存） */
  onUpdated: (u: User) => void;
}

interface FormValues {
  email?: string;
  phone?: string;
}

/** 个人设置：维护联系方式；用户名与密码等账号凭据由成员管理统一维护。 */
export default function SelfSettingsModal({ open, user, onClose, onUpdated }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        email: user?.email ?? '',
        phone: user?.phone ?? '',
      });
    }
  }, [open, user, form]);

  const submit = async () => {
    const v = await form.validateFields();
    setSaving(true);
    try {
      const updated = await apiFetch<User>('/api/me', {
        method: 'PUT',
        body: JSON.stringify({ email: v.email ?? '', phone: v.phone ?? '' }),
      });
      onUpdated(updated);
      message.success('资料已更新');
      onClose();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="个人设置"
      open={open}
      onOk={submit}
      onCancel={onClose}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
        <Form.Item label="用户名">
          <Input value={user?.username ?? ''} disabled prefix={<LockOutlined />} />
        </Form.Item>
        <Form.Item
          name="email"
          label="邮箱"
          rules={[{ type: 'email', message: '邮箱格式不正确' }]}
        >
          <Input placeholder="用于接收通知（选填）" prefix={<MailOutlined />} allowClear />
        </Form.Item>
        <Form.Item name="phone" label="手机号">
          <Input placeholder="用于联系确认（选填）" prefix={<PhoneOutlined />} allowClear />
        </Form.Item>
      </Form>
    </Modal>
  );
}
