'use client';

import { useEffect, useState } from 'react';
import { Alert, App, Badge, Card, Empty, List, Skeleton, Typography } from 'antd';
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
    <AppLayout title="通知中心" subtitle="推荐商机与系统消息，点击未读项标记为已读">
      <Card className="compass-card">
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        {loading ? (
          <Skeleton active paragraph={{ rows: 5 }} />
        ) : (
          <List
            dataSource={items}
            locale={{
              emptyText: <Empty description="暂无通知，订阅生效后新商机将推送到这里" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
            }}
            renderItem={(item) => (
              <List.Item
                className={`notif-item ${item.read ? '' : 'notif-item-unread'}`}
                onClick={() => markRead(item)}
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
                      <Typography.Text
                        strong={!item.read}
                        style={item.read ? { color: 'rgba(0, 0, 0, 0.45)' } : undefined}
                      >
                        {item.title}
                      </Typography.Text>
                    </span>
                  }
                  description={
                    <span style={{ color: item.read ? 'rgba(0, 0, 0, 0.35)' : 'rgba(0, 0, 0, 0.55)' }}>
                      {item.body}
                    </span>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>
    </AppLayout>
  );
}
