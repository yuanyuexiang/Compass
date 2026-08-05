'use client';

import { useEffect, useState } from 'react';
import { App, Divider, Form, Input, Modal, Typography } from 'antd';
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
  old_password?: string;
  new_password?: string;
  confirm?: string;
}

/** 个人设置：任何登录用户自助修改邮箱与密码（用户名是登录标识不可改） */
export default function SelfSettingsModal({ open, user, onClose, onUpdated }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        email: user?.email ?? '',
        phone: user?.phone ?? '',
        old_password: '',
        new_password: '',
        confirm: '',
      });
    }
  }, [open, user, form]);

  const submit = async () => {
    const v = await form.validateFields();
    const wantsPassword = Boolean(v.old_password || v.new_password || v.confirm);
    setSaving(true);
    try {
      if (wantsPassword) {
        await apiFetch('/api/me/password', {
          method: 'POST',
          body: JSON.stringify({ old_password: v.old_password, new_password: v.new_password }),
        });
      }
      const updated = await apiFetch<User>('/api/me', {
        method: 'PUT',
        body: JSON.stringify({ email: v.email ?? '', phone: v.phone ?? '' }),
      });
      onUpdated(updated);
      message.success(wantsPassword ? '资料已更新，密码修改成功' : '资料已更新');
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

        <Divider style={{ margin: '12px 0' }} />
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
          修改密码（不改则留空）：至少 8 位，须包含字母和数字
        </Typography.Text>
        <Form.Item
          name="old_password"
          label="原密码"
          dependencies={['new_password', 'confirm']}
          rules={[
            ({ getFieldValue }) => ({
              validator: (_, value) =>
                (getFieldValue('new_password') || getFieldValue('confirm')) && !value
                  ? Promise.reject(new Error('请输入原密码'))
                  : Promise.resolve(),
            }),
          ]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="新密码"
          dependencies={['old_password']}
          rules={[
            ({ getFieldValue }) => ({
              validator: (_, value) => {
                if (!value) {
                  return getFieldValue('old_password')
                    ? Promise.reject(new Error('请输入新密码'))
                    : Promise.resolve();
                }
                if (value.length < 8 || !/[A-Za-z]/.test(value) || !/\d/.test(value)) {
                  return Promise.reject(new Error('至少 8 位，须包含字母和数字'));
                }
                return Promise.resolve();
              },
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="确认新密码"
          dependencies={['new_password']}
          rules={[
            ({ getFieldValue }) => ({
              validator: (_, value) =>
                value === getFieldValue('new_password')
                  ? Promise.resolve()
                  : Promise.reject(new Error('两次输入的新密码不一致')),
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
