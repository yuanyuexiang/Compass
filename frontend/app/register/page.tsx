'use client';

import { useState } from 'react';
import Link from 'next/link';
import { App, Button, Card, Form, Input, Result, Typography } from 'antd';
import { BankOutlined, CompassOutlined, LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons';
import { apiFetch } from '@/lib/api';

interface RegisterForm {
  tenant_name: string;
  username: string;
  password: string;
  confirm: string;
  email?: string;
}

export default function RegisterPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const onFinish = async (values: RegisterForm) => {
    setLoading(true);
    try {
      await apiFetch('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          tenant_name: values.tenant_name.trim(),
          username: values.username.trim(),
          password: values.password,
          email: values.email || null,
        }),
      });
      setSubmitted(true);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="compass-login-bg">
      <Card
        style={{ width: 440, borderRadius: 16, zIndex: 1, boxShadow: '0 8px 40px rgba(15, 27, 61, 0.35)' }}
        styles={{ body: { padding: '36px 32px 28px' } }}
      >
        {submitted ? (
          <Result
            status="success"
            title="申请已提交"
            subTitle="平台管理员审批通过后即可登录，请留意通知。"
            extra={
              <Link href="/login">
                <Button type="primary">返回登录</Button>
              </Link>
            }
          />
        ) : (
          <>
            <div style={{ textAlign: 'center', marginBottom: 24 }}>
              <CompassOutlined style={{ fontSize: 44, color: '#FAAD14' }} />
              <Typography.Title level={3} style={{ margin: '12px 0 4px' }}>
                申请企业开通
              </Typography.Title>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                提交后由平台管理员审批，通过即可登录使用
              </Typography.Text>
            </div>
            <Form<RegisterForm> layout="vertical" onFinish={onFinish} size="large">
              <Form.Item
                name="tenant_name"
                rules={[
                  { required: true, message: '请输入企业名称' },
                  { min: 2, message: '企业名称至少 2 个字' },
                ]}
              >
                <Input prefix={<BankOutlined />} placeholder="企业名称（营业执照全称）" />
              </Form.Item>
              <Form.Item
                name="username"
                rules={[
                  { required: true, message: '请输入管理员用户名' },
                  { min: 2, message: '用户名至少 2 个字符' },
                ]}
              >
                <Input prefix={<UserOutlined />} placeholder="管理员用户名" autoComplete="username" />
              </Form.Item>
              <Form.Item name="email" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
                <Input prefix={<MailOutlined />} placeholder="联系邮箱（选填）" autoComplete="email" />
              </Form.Item>
              <Form.Item
                name="password"
                rules={[
                  { required: true, message: '请输入密码' },
                  {
                    pattern: /^(?=.*[A-Za-z])(?=.*\d).{8,}$/,
                    message: '至少 8 位，需同时包含字母和数字',
                  },
                ]}
              >
                <Input.Password prefix={<LockOutlined />} placeholder="密码（至少 8 位，含字母和数字）" autoComplete="new-password" />
              </Form.Item>
              <Form.Item
                name="confirm"
                dependencies={['password']}
                rules={[
                  { required: true, message: '请再次输入密码' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue('password') === value) return Promise.resolve();
                      return Promise.reject(new Error('两次输入的密码不一致'));
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined />} placeholder="确认密码" autoComplete="new-password" />
              </Form.Item>
              <Form.Item style={{ marginBottom: 8 }}>
                <Button type="primary" htmlType="submit" block loading={loading} style={{ height: 44, fontSize: 15 }}>
                  提交申请
                </Button>
              </Form.Item>
            </Form>
            <div style={{ textAlign: 'center', marginTop: 4 }}>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                已有账号？<Link href="/login">直接登录</Link>
              </Typography.Text>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
