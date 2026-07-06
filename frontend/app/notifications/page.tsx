'use client';

import { useEffect, useState } from 'react';
import { Alert, App, Badge, Card, List, Spin, Typography } from 'antd';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import type { NotificationItem } from '@/lib/types';

export default function NotificationsPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<NotificationItem[]>('/api/notifications?limit=100')
      .then((data) => {
        setItems(data ?? []);
        setError(null);
      })
      .catch((e: Error) => {
        setItems([]);
        setError(e.message);
      })
      .finally(() => setLoading(false));
  }, []);

  const markRead = async (item: NotificationItem) => {
    if (item.read) return;
    setItems((list) => list.map((n) => (n.id === item.id ? { ...n, read: true } : n)));
    try {
      await apiFetch<{ ok: boolean }>(`/api/notifications/${item.id}/read`, { method: 'POST' });
    } catch (e) {
      setItems((list) => list.map((n) => (n.id === item.id ? { ...n, read: false } : n)));
      message.error((e as Error).message);
    }
  };

  return (
    <AppLayout>
      <Card title="通知中心">
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
          </div>
        ) : (
          <List
            dataSource={items}
            locale={{ emptyText: '暂无通知' }}
            renderItem={(item) => (
              <List.Item
                onClick={() => markRead(item)}
                style={{ cursor: item.read ? 'default' : 'pointer' }}
                extra={
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {item.created_at}
                  </Typography.Text>
                }
              >
                <List.Item.Meta
                  title={
                    <span>
                      {!item.read ? <Badge status="processing" style={{ marginRight: 8 }} /> : null}
                      <Typography.Text strong={!item.read}>{item.title}</Typography.Text>
                    </span>
                  }
                  description={item.body}
                />
              </List.Item>
            )}
          />
        )}
      </Card>
    </AppLayout>
  );
}
