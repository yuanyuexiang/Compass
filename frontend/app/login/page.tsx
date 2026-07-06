'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { App, Button, Card, Form, Input, Typography } from 'antd';
import { CompassOutlined, LockOutlined, UserOutlined } from '@ant-design/icons';
import { apiFetch, getToken, setSession } from '@/lib/api';
import type { LoginResponse } from '@/lib/types';

interface LoginForm {
  username: string;
  password: string;
}

export default function LoginPage() {
  const router = useRouter();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace('/');
  }, [router]);

  const onFinish = async (values: LoginForm) => {
    setLoading(true);
    try {
      const res = await apiFetch<LoginResponse>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify(values),
      });
      setSession(res.access_token, res.user);
      message.success('登录成功');
      router.replace('/');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f0f2f5',
      }}
    >
      <Card style={{ width: 380 }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            <CompassOutlined /> 司南 · AI 寻标 Agent
          </Typography.Title>
          <Typography.Text type="secondary">招投标商机智能推荐平台</Typography.Text>
        </div>
        <Form<LoginForm> layout="vertical" onFinish={onFinish}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
