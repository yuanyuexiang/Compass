'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { App, Button, Card, Divider, Form, Input, Typography } from 'antd';
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
    <div className="compass-login-bg">
      <Card
        style={{
          width: 400,
          borderRadius: 16,
          zIndex: 1,
          boxShadow: '0 8px 40px rgba(15, 27, 61, 0.35)',
        }}
        styles={{ body: { padding: '36px 32px 28px' } }}
      >
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <CompassOutlined style={{ fontSize: 48, color: '#FAAD14' }} />
          <Typography.Title level={3} style={{ margin: '12px 0 4px' }}>
            司南 · AI 寻标 Agent
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            AI 主动发现商机
          </Typography.Text>
        </div>
        <Form<LoginForm> layout="vertical" onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" block loading={loading} style={{ height: 44, fontSize: 15 }}>
              登 录
            </Button>
          </Form.Item>
        </Form>
        {/* 演示账号提示仅开发模式显示（生产构建时 NODE_ENV=production，此块被裁掉） */}
        {process.env.NODE_ENV === 'development' && (
          <>
            <Divider plain style={{ margin: '12px 0' }} />
            <div style={{ textAlign: 'center' }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                演示账号：admin / admin123
              </Typography.Text>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
