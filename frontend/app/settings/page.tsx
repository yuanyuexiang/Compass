'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { Alert, App, Button, Card, Col, Form, Input, Rate, Row, Skeleton, Space, Switch, Typography } from 'antd';
import {
  DingtalkOutlined,
  MailOutlined,
  SaveOutlined,
  SendOutlined,
  WechatWorkOutlined,
} from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import type { SubscriptionData } from '@/lib/types';

type ChannelKey = 'email' | 'wecom' | 'dingtalk' | 'feishu';

const CHANNELS: {
  key: ChannelKey;
  label: string;
  icon: ReactNode;
  field: 'address' | 'webhook';
  fieldLabel: string;
  placeholder: string;
}[] = [
  {
    key: 'email',
    label: '邮件',
    icon: <MailOutlined style={{ color: '#2F54EB' }} />,
    field: 'address',
    fieldLabel: '收件地址',
    placeholder: 'name@example.com',
  },
  {
    key: 'wecom',
    label: '企业微信',
    icon: <WechatWorkOutlined style={{ color: '#2F54EB' }} />,
    field: 'webhook',
    fieldLabel: 'Webhook 地址',
    placeholder: 'https://qyapi.weixin.qq.com/...',
  },
  {
    key: 'dingtalk',
    label: '钉钉',
    icon: <DingtalkOutlined style={{ color: '#2F54EB' }} />,
    field: 'webhook',
    fieldLabel: 'Webhook 地址',
    placeholder: 'https://oapi.dingtalk.com/...',
  },
  {
    key: 'feishu',
    label: '飞书',
    icon: <SendOutlined style={{ color: '#2F54EB' }} />,
    field: 'webhook',
    fieldLabel: 'Webhook 地址',
    placeholder: 'https://open.feishu.cn/...',
  },
];

const DEFAULT_VALUES: SubscriptionData = {
  min_star: 4,
  immediate: true,
  daily_digest: true,
  channels: {
    email: { enabled: false, address: '' },
    wecom: { enabled: false, webhook: '' },
    dingtalk: { enabled: false, webhook: '' },
    feishu: { enabled: false, webhook: '' },
  },
};

export default function SettingsPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm<SubscriptionData>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<SubscriptionData>('/api/subscriptions')
      .then((data) => {
        form.setFieldsValue(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [form]);

  const onFinish = async (values: SubscriptionData) => {
    const payload: SubscriptionData = {
      min_star: values.min_star ?? DEFAULT_VALUES.min_star,
      immediate: values.immediate ?? false,
      daily_digest: values.daily_digest ?? false,
      channels: {
        email: {
          enabled: values.channels?.email?.enabled ?? false,
          address: values.channels?.email?.address ?? '',
        },
        wecom: {
          enabled: values.channels?.wecom?.enabled ?? false,
          webhook: values.channels?.wecom?.webhook ?? '',
        },
        dingtalk: {
          enabled: values.channels?.dingtalk?.enabled ?? false,
          webhook: values.channels?.dingtalk?.webhook ?? '',
        },
        feishu: {
          enabled: values.channels?.feishu?.enabled ?? false,
          webhook: values.channels?.feishu?.webhook ?? '',
        },
      },
    };
    setSaving(true);
    try {
      await apiFetch<{ ok: boolean }>('/api/subscriptions', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      message.success('订阅设置已保存');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppLayout title="订阅设置" subtitle="设定推送阈值与通知渠道，高星商机不再错过">
      {error ? (
        <Alert
          type="warning"
          showIcon
          message="订阅设置加载失败，可直接修改后保存"
          description={error}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {loading ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card className="compass-card">
            <Skeleton active paragraph={{ rows: 2 }} />
          </Card>
          <Card className="compass-card">
            <Skeleton active paragraph={{ rows: 4 }} />
          </Card>
        </Space>
      ) : null}
      {/* Form 始终挂载（加载时隐藏），避免 useForm 实例未连接的警告 */}
      <div style={{ display: loading ? 'none' : undefined }}>
        <Form<SubscriptionData> form={form} layout="vertical" initialValues={DEFAULT_VALUES} onFinish={onFinish}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card className="compass-card" title="推送策略">
              <Form.Item name="min_star" label="星级阈值（达到该星级才推送）">
                <Rate />
              </Form.Item>
              <Row gutter={40}>
                <Col>
                  <Form.Item name="immediate" label="即时提醒" valuePropName="checked" style={{ marginBottom: 0 }}>
                    <Switch />
                  </Form.Item>
                </Col>
                <Col>
                  <Form.Item name="daily_digest" label="每日日报" valuePropName="checked" style={{ marginBottom: 0 }}>
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>
            </Card>

            <Card className="compass-card" title="通知渠道">
              <Row gutter={[16, 16]}>
                {CHANNELS.map((ch) => (
                  <Col xs={24} md={12} key={ch.key}>
                    <Card
                      size="small"
                      style={{ background: '#FAFBFD' }}
                      title={
                        <Space size={8}>
                          {ch.icon}
                          <Typography.Text strong>{ch.label}</Typography.Text>
                        </Space>
                      }
                      extra={
                        <Form.Item name={['channels', ch.key, 'enabled']} valuePropName="checked" noStyle>
                          <Switch size="small" />
                        </Form.Item>
                      }
                    >
                      <Form.Item
                        name={['channels', ch.key, ch.field]}
                        label={ch.fieldLabel}
                        style={{ marginBottom: 0 }}
                      >
                        <Input placeholder={ch.placeholder} />
                      </Form.Item>
                    </Card>
                  </Col>
                ))}
              </Row>
            </Card>

            <Button type="primary" htmlType="submit" loading={saving} icon={<SaveOutlined />} size="large">
              保存设置
            </Button>
          </Space>
        </Form>
      </div>
    </AppLayout>
  );
}
