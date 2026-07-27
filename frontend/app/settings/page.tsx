'use client';

import { useEffect, useState, type ReactNode } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  List,
  Modal,
  Rate,
  Row,
  Select,
  Skeleton,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd';
import {
  CloudDownloadOutlined,
  DingtalkOutlined,
  MailOutlined,
  PlusOutlined,
  SaveOutlined,
  SendOutlined,
  WechatWorkOutlined,
} from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import type { SourceOption, SourceRequestItem, SubscriptionData } from '@/lib/types';

const REQUEST_STATUS_TAG: Record<SourceRequestItem['status'], { color: string; label: string }> = {
  pending: { color: 'gold', label: '待审批' },
  active: { color: 'green', label: '已通过' },
  rejected: { color: 'red', label: '已驳回' },
};

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
  source_ids: [],
};

export default function SettingsPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm<SubscriptionData>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceOptions, setSourceOptions] = useState<SourceOption[]>([]);
  const [myRequests, setMyRequests] = useState<SourceRequestItem[]>([]);
  const [requestOpen, setRequestOpen] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [requestForm] = Form.useForm<{ url: string; display_name: string; note: string }>();

  const loadRequests = () => {
    apiFetch<SourceRequestItem[]>('/api/sources/requests/mine')
      .then(setMyRequests)
      .catch(() => {
        // 申请列表拉取失败不阻塞订阅设置
      });
  };

  useEffect(() => {
    apiFetch<SubscriptionData>('/api/subscriptions')
      .then((data) => {
        form.setFieldsValue(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
    apiFetch<SourceOption[]>('/api/sources/options')
      .then(setSourceOptions)
      .catch(() => {
        // 源列表拉取失败仅影响下拉选项展示，不阻塞订阅设置
      });
    loadRequests();
  }, [form]);

  const submitRequest = async () => {
    const values = await requestForm.validateFields();
    setRequesting(true);
    try {
      await apiFetch('/api/sources/requests', { method: 'POST', body: JSON.stringify(values) });
      message.success('申请已提交，管理员审批通过后即开始采集');
      setRequestOpen(false);
      requestForm.resetFields();
      loadRequests();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setRequesting(false);
    }
  };

  const onFinish = async (values: SubscriptionData) => {
    const payload: SubscriptionData = {
      min_star: values.min_star ?? DEFAULT_VALUES.min_star,
      immediate: values.immediate ?? false,
      daily_digest: values.daily_digest ?? false,
      source_ids: values.source_ids ?? [],
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

            <Card
              className="compass-card"
              title={
                <Space size={8}>
                  <CloudDownloadOutlined style={{ color: '#2F54EB' }} />
                  <span>关注的数据源</span>
                </Space>
              }
              extra={
                <Button icon={<PlusOutlined />} onClick={() => setRequestOpen(true)}>
                  申请新数据源
                </Button>
              }
            >
              <Form.Item
                name="source_ids"
                label="只看这些采集平台的公告（商机查询与智能推荐同时生效）"
                extra="不选 = 全部数据源。缺你要的平台？点右上角「申请新数据源」，管理员审批通过后即可勾选。"
                style={{ marginBottom: 0 }}
              >
                <Select
                  mode="multiple"
                  allowClear
                  placeholder="全部数据源"
                  options={sourceOptions.map((s) => ({
                    value: s.id,
                    label: s.enabled ? s.display_name : `${s.display_name}（已停采）`,
                  }))}
                />
              </Form.Item>
              {myRequests.length > 0 ? (
                <List
                  size="small"
                  style={{ marginTop: 16 }}
                  header={<Typography.Text strong>我提交的申请</Typography.Text>}
                  dataSource={myRequests}
                  renderItem={(r) => (
                    <List.Item>
                      <Space size={8} wrap>
                        <Tag color={REQUEST_STATUS_TAG[r.status].color}>
                          {REQUEST_STATUS_TAG[r.status].label}
                        </Tag>
                        <Typography.Text strong>{r.display_name}</Typography.Text>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {r.url}
                        </Typography.Text>
                        {r.status === 'rejected' && r.reject_reason ? (
                          <Typography.Text type="danger" style={{ fontSize: 12 }}>
                            理由：{r.reject_reason}
                          </Typography.Text>
                        ) : null}
                      </Space>
                    </List.Item>
                  )}
                />
              ) : null}
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

      <Modal
        title="申请新数据源"
        open={requestOpen}
        onOk={submitRequest}
        onCancel={() => setRequestOpen(false)}
        confirmLoading={requesting}
        okText="提交申请"
        cancelText="取消"
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          填写你希望平台采集的公告网站，管理员审批通过后即开始采集，届时可在「关注的数据源」中勾选。
        </Typography.Paragraph>
        <Form form={requestForm} layout="vertical">
          <Form.Item
            name="url"
            label="公告列表页网址"
            rules={[
              { required: true, message: '请填写网址' },
              { pattern: /^https?:\/\//, message: '网址须以 http(s):// 开头' },
            ]}
          >
            <Input placeholder="https://例：某省公共资源交易平台的招标公告列表页" />
          </Form.Item>
          <Form.Item
            name="display_name"
            label="平台名称"
            rules={[{ required: true, min: 2, message: '请填写平台名称（至少 2 个字）' }]}
          >
            <Input placeholder="例：广东省政府采购网" maxLength={128} />
          </Form.Item>
          <Form.Item name="note" label="申请说明（选填）">
            <Input.TextArea
              rows={3}
              maxLength={500}
              placeholder="例：我们主要投这个平台的标，希望第一时间收到推荐"
            />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  );
}
