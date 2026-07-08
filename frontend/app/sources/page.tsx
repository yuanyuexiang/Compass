'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CloudDownloadOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import { formatDateTime } from '@/lib/labels';

interface SourceItem {
  id: number;
  name: string;
  display_name: string;
  adapter: string;
  adapter_display_name: string;
  enabled: boolean;
  min_interval_seconds: number;
  config: Record<string, unknown>;
  last_run_at: string | null;
  announcement_count: number;
}

interface AdapterItem {
  name: string;
  display_name: string;
}

/** 各适配器的 config 示例模板（新增源时按所选适配器预填） */
const CONFIG_TEMPLATES: Record<string, object> = {
  ccgp: {
    channels: ['https://www.ccgp.gov.cn/cggg/zygg/', 'https://www.ccgp.gov.cn/cggg/dfgg/'],
  },
  jsggzy: {
    categorynums: ['003001001', '003002001', '003003001', '003004002'],
    rows_per_category: 20,
  },
};

export default function SourcesPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<SourceItem[]>([]);
  const [adapters, setAdapters] = useState<AdapterItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SourceItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    try {
      const [sources, adapterList] = await Promise.all([
        apiFetch<SourceItem[]>('/api/sources'),
        apiFetch<AdapterItem[]>('/api/sources/adapters'),
      ]);
      setItems(sources);
      setAdapters(adapterList);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleEnabled = async (record: SourceItem, enabled: boolean) => {
    setItems((prev) => prev.map((s) => (s.id === record.id ? { ...s, enabled } : s)));
    try {
      await apiFetch(`/api/sources/${record.id}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
      message.success(enabled ? `已启用 ${record.display_name}` : `已停用 ${record.display_name}`);
    } catch (e) {
      setItems((prev) => prev.map((s) => (s.id === record.id ? { ...s, enabled: !enabled } : s)));
      message.error(e instanceof Error ? e.message : '操作失败');
    }
  };

  const triggerCrawl = async (record?: SourceItem) => {
    try {
      await apiFetch(record ? `/api/sources/${record.id}/crawl` : '/api/sources/crawl-all', {
        method: 'POST',
      });
      message.success(
        `${record ? record.display_name : '全部数据源'}采集已入队，约 1–2 分钟后可在商机查询查看新数据`,
      );
    } catch (e) {
      message.error(e instanceof Error ? e.message : '触发失败');
    }
  };

  const openModal = (record: SourceItem | null) => {
    setEditing(record);
    setModalOpen(true);
    form.setFieldsValue(
      record
        ? {
            name: record.name,
            display_name: record.display_name,
            adapter: record.adapter,
            min_interval_seconds: record.min_interval_seconds,
            config: JSON.stringify(record.config ?? {}, null, 2),
          }
        : { name: '', display_name: '', adapter: undefined, min_interval_seconds: 3, config: '{}' },
    );
  };

  const onAdapterChange = (adapter: string) => {
    const current = (form.getFieldValue('config') as string | undefined)?.trim();
    if (!editing && (!current || current === '{}')) {
      form.setFieldsValue({ config: JSON.stringify(CONFIG_TEMPLATES[adapter] ?? {}, null, 2) });
    }
  };

  const submit = async () => {
    const values = await form.validateFields();
    let config: object;
    try {
      config = JSON.parse(values.config || '{}');
    } catch {
      message.error('config 不是合法的 JSON');
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await apiFetch(`/api/sources/${editing.id}`, {
          method: 'PUT',
          body: JSON.stringify({
            display_name: values.display_name,
            min_interval_seconds: values.min_interval_seconds,
            config,
          }),
        });
      } else {
        await apiFetch('/api/sources', {
          method: 'POST',
          body: JSON.stringify({
            name: values.name,
            display_name: values.display_name,
            adapter: values.adapter,
            min_interval_seconds: values.min_interval_seconds,
            config,
          }),
        });
      }
      message.success(editing ? '已保存' : '数据源已创建');
      setModalOpen(false);
      void load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<SourceItem> = [
    {
      title: '数据源',
      dataIndex: 'display_name',
      key: 'display_name',
      render: (v: string, record) => (
        <div>
          <strong>{v}</strong>
          <div style={{ fontSize: 12, color: 'rgba(0,0,0,.45)' }}>{record.name}</div>
        </div>
      ),
    },
    {
      title: '平台',
      dataIndex: 'adapter_display_name',
      key: 'adapter',
      width: 190,
      render: (v: string, record) => <Tag color="geekblue">{v || record.adapter}</Tag>,
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (v: boolean, record) => <Switch checked={v} onChange={(c) => toggleEnabled(record, c)} />,
    },
    {
      title: '上次采集',
      dataIndex: 'last_run_at',
      key: 'last_run_at',
      width: 150,
      render: (v: string | null) => formatDateTime(v),
    },
    {
      title: '累计公告',
      dataIndex: 'announcement_count',
      key: 'announcement_count',
      width: 100,
      align: 'right',
    },
    { title: '限速(秒/请求)', dataIndex: 'min_interval_seconds', key: 'min_interval_seconds', width: 120, align: 'right' },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            type="primary"
            ghost
            icon={<ThunderboltOutlined />}
            disabled={!record.enabled}
            onClick={() => triggerCrawl(record)}
          >
            立即采集
          </Button>
          <Button size="small" onClick={() => openModal(record)}>
            编辑
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout title="采集管理" subtitle="数据源配置、启停与手动触发（自动调度每 30 分钟一轮）">
      {error ? <Alert type="warning" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      <Card
        className="compass-card"
        title="数据源"
        extra={
          <Space>
            <Button icon={<CloudDownloadOutlined />} onClick={() => triggerCrawl()}>
              全部采集
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>
              新增数据源
            </Button>
          </Space>
        }
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : (
          <Table<SourceItem>
            rowKey="id"
            columns={columns}
            dataSource={items}
            pagination={false}
            size="middle"
            locale={{ emptyText: <Empty description="暂无数据源，点击右上角新增" /> }}
          />
        )}
      </Card>

      <Modal
        title={editing ? `编辑数据源：${editing.name}` : '新增数据源'}
        open={modalOpen}
        onOk={submit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText={editing ? '保存' : '创建'}
        width={560}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            name="display_name"
            label="中文名称"
            rules={[{ required: true, message: '请输入中文名称' }]}
          >
            <Input placeholder="如 江苏公共资源·政府采购公告" />
          </Form.Item>
          <Form.Item
            name="name"
            label="标识（唯一，用于日志与排查）"
            rules={[{ required: true, message: '请输入标识' }]}
          >
            <Input placeholder="如 jsggzy-zfcg" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="adapter" label="平台适配器" rules={[{ required: true, message: '请选择平台' }]}>
            <Select
              placeholder="选择采集平台"
              options={adapters.map((a) => ({
                value: a.name,
                label: `${a.display_name}（${a.name}）`,
              }))}
              onChange={onAdapterChange}
              disabled={!!editing}
            />
          </Form.Item>
          <Form.Item name="min_interval_seconds" label="限速（每次请求最小间隔，秒）">
            <InputNumber min={1} max={60} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="config" label="采集配置（JSON，按适配器自动给出模板）">
            <Input.TextArea rows={7} style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </Form.Item>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            同一适配器可建多个源实例（如 jsggzy 按类目拆分）；新平台需先在后端实现适配器。
          </Typography.Text>
        </Form>
      </Modal>
    </AppLayout>
  );
}
