'use client';

import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Col, Empty, List, Popconfirm, Row, Segmented, Skeleton, Space, Typography } from 'antd';
import { BellFilled, ClockCircleOutlined, DeleteOutlined, ProjectOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import OpportunityDetailPanel from '@/components/OpportunityDetailPanel';
import { apiFetch } from '@/lib/api';
import { formatDateTime } from '@/lib/labels';
import type { NotificationItem } from '@/lib/types';

export default function NotificationsPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | string | null>(null);
  const [filter, setFilter] = useState<'all' | 'unread'>('all');

  useEffect(() => {
    apiFetch<NotificationItem[]>('/api/notifications?limit=100')
      .then((data) => {
        setItems(data ?? []);
        setSelectedId((current) => current ?? data?.[0]?.id ?? null);
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
      window.dispatchEvent(new Event('compass:notifications-changed'));
    } catch (e) {
      setItems((list) => list.map((n) => (n.id === item.id ? { ...n, read: false } : n)));
      message.error((e as Error).message);
    }
  };

  const remove = async (item: NotificationItem) => {
    try {
      await apiFetch<{ ok: boolean }>(`/api/notifications/${item.id}`, { method: 'DELETE' });
      const nextItems = items.filter((notification) => String(notification.id) !== String(item.id));
      setItems(nextItems);
      if (String(selectedId) === String(item.id)) {
        const currentIndex = items.findIndex((notification) => String(notification.id) === String(item.id));
        setSelectedId(nextItems[Math.min(currentIndex, nextItems.length - 1)]?.id ?? null);
      }
      window.dispatchEvent(new Event('compass:notifications-changed'));
      message.success('通知已删除');
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const visibleItems = filter === 'unread' ? items.filter((item) => !item.read) : items;
  const selected = items.find((item) => String(item.id) === String(selectedId)) ?? null;

  return (
    <AppLayout title="通知中心" subtitle="推荐商机与系统消息，点击未读项标记为已读">
      <Row gutter={[16, 16]} align="stretch" className="list-detail-layout">
        <Col xs={24} lg={9} xl={8}>
      <Card className="compass-card notification-inbox" styles={{ body: { padding: 0 } }}>
        <div className="notification-inbox-head">
          <div className="notification-summary-icon"><BellFilled /></div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Typography.Text strong style={{ display: 'block', fontSize: 16 }}>消息中心</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {items.filter((item) => !item.read).length ? `${items.filter((item) => !item.read).length} 条消息等待查看` : '所有消息均已查看'}
            </Typography.Text>
          </div>
        </div>
        <div className="notification-filter">
          <Segmented
            block
            value={filter}
            onChange={(value) => setFilter(value as 'all' | 'unread')}
            options={[{ label: `全部 ${items.length}`, value: 'all' }, { label: `未读 ${items.filter((item) => !item.read).length}`, value: 'unread' }]}
          />
        </div>
        <div className="notification-list-wrap">
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        {loading ? (
          <Skeleton active paragraph={{ rows: 5 }} />
        ) : (
          <List
            dataSource={visibleItems}
            locale={{
              emptyText: <Empty description="暂无通知，订阅生效后新商机将推送到这里" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
            }}
            renderItem={(item) => (
              <List.Item
                className={`notification-row${item.read ? '' : ' notification-row-unread'}${String(item.id) === String(selectedId) ? ' notification-row-active' : ''}`}
                onClick={() => {
                  setSelectedId(item.id);
                  void markRead(item);
                }}
                extra={
                  <Popconfirm
                    title="删除这条通知？"
                    description="关联商机和跟进记录不会被删除。"
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    onConfirm={(event) => {
                      event?.stopPropagation();
                      void remove(item);
                    }}
                  >
                    <Button
                      type="text"
                      danger
                      size="small"
                      className="notification-delete"
                      aria-label="删除通知"
                      icon={<DeleteOutlined />}
                      onClick={(event) => event.stopPropagation()}
                    />
                  </Popconfirm>
                }
              >
                <List.Item.Meta
                  avatar={
                    <div className="notification-row-icon">
                      {item.announcement_id ? <ProjectOutlined /> : <BellFilled />}
                    </div>
                  }
                  title={
                    <div className="notification-row-title">
                      <Typography.Text
                        strong={!item.read}
                        ellipsis
                        style={item.read ? { color: 'rgba(0, 0, 0, 0.58)', maxWidth: '100%' } : { maxWidth: '100%' }}
                      >
                        {item.title}
                      </Typography.Text>
                      {!item.read ? <span className="notification-unread-dot" /> : null}
                    </div>
                  }
                  description={
                    <Space direction="vertical" size={5} style={{ width: '100%' }}>
                      <span className="notification-row-body">{item.body}</span>
                      <span className="notification-row-time"><ClockCircleOutlined /> {formatDateTime(item.created_at)}</span>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
        </div>
      </Card>
        </Col>
        <Col xs={24} lg={15} xl={16}>
          {selected?.announcement_id ? (
            <OpportunityDetailPanel key={selected.id} id={selected.announcement_id} />
          ) : (
            <Card key={selected?.id ?? 'empty'} className="compass-card opportunity-detail">
              <Empty description={selected ? '这是一条系统通知，没有关联商机' : '从左侧选择一条通知'} />
            </Card>
          )}
        </Col>
      </Row>
    </AppLayout>
  );
}
