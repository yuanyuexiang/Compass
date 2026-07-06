'use client';

import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Col, Form, Input, Rate, Row, Spin, Switch, Typography } from 'antd';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import type { SubscriptionData } from '@/lib/types';

type WebhookKey = 'wecom' | 'dingtalk' | 'feishu';

const WEBHOOK_CHANNELS: { key: WebhookKey; label: string }[] = [
  { key: 'wecom', label: '企业微信' },
  { key: 'dingtalk', label: '钉钉' },
  { key: 'feishu', label: '飞书' },
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
    <AppLayout>
      <Card title="订阅设置">
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
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
          </div>
        ) : (
          <Form<SubscriptionData> form={form} layout="vertical" initialValues={DEFAULT_VALUES} onFinish={onFinish}>
            <Form.Item name="min_star" label="推送星级阈值（达到该星级才推送）">
              <Rate />
            </Form.Item>
            <Row gutter={24}>
              <Col>
                <Form.Item name="immediate" label="即时提醒" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </Col>
              <Col>
                <Form.Item name="daily_digest" label="每日日报" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </Col>
            </Row>
            <Typography.Title level={5}>通知渠道</Typography.Title>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={12}>
                <Card size="small" title="邮件">
                  <Form.Item name={['channels', 'email', 'enabled']} label="启用" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item name={['channels', 'email', 'address']} label="收件地址" style={{ marginBottom: 0 }}>
                    <Input placeholder="name@example.com" />
                  </Form.Item>
                </Card>
              </Col>
              {WEBHOOK_CHANNELS.map((ch) => (
                <Col xs={24} md={12} key={ch.key}>
                  <Card size="small" title={ch.label}>
                    <Form.Item name={['channels', ch.key, 'enabled']} label="启用" valuePropName="checked">
                      <Switch />
                    </Form.Item>
                    <Form.Item name={['channels', ch.key, 'webhook']} label="Webhook 地址" style={{ marginBottom: 0 }}>
                      <Input placeholder="https://..." />
                    </Form.Item>
                  </Card>
                </Col>
              ))}
            </Row>
            <Form.Item style={{ marginTop: 24, marginBottom: 0 }}>
              <Button type="primary" htmlType="submit" loading={saving}>
                保存设置
              </Button>
            </Form.Item>
          </Form>
        )}
      </Card>
    </AppLayout>
  );
}
