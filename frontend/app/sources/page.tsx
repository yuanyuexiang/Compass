'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CloudDownloadOutlined,
  DeleteOutlined,
  PlusOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
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

interface ScheduleInfo {
  interval_minutes: number;
  last_auto_crawl_at: string | null;
}

/** 江苏公共资源交易平台的采集类目（类目号 → 中文名，供多选框展示） */
const JSGGZY_CATEGORIES = [
  { value: '003001001', label: '建设工程' },
  { value: '003002001', label: '交通工程' },
  { value: '003003001', label: '水利工程' },
  { value: '003004002', label: '政府采购' },
  { value: '003009001', label: '其他交易' },
  { value: '003010001', label: '药品耗材' },
  { value: '003011001', label: '机电设备' },
];

interface TestResult {
  ok: boolean;
  error?: string;
  items: { title: string; url: string; publish_time: string | null; region: string | null }[];
  detail_preview: { content_excerpt: string; content_length: number } | null;
}

interface SmartResult extends TestResult {
  adapter: string;
  adapter_display_name: string;
  config: Record<string, unknown> | null;
  notes?: string;
}

export default function SourcesPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<SourceItem[]>([]);
  const [adapters, setAdapters] = useState<AdapterItem[]>([]);
  const [schedule, setSchedule] = useState<ScheduleInfo | null>(null);
  const [intervalInput, setIntervalInput] = useState<number>(30);
  const [savingInterval, setSavingInterval] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SourceItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [smartUrl, setSmartUrl] = useState('');
  const [smartDetecting, setSmartDetecting] = useState(false);
  const [smartResult, setSmartResult] = useState<SmartResult | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [form] = Form.useForm();
  const watchedAdapter = Form.useWatch('adapter', form);

  const load = useCallback(async () => {
    try {
      const [sources, adapterList, sched] = await Promise.all([
        apiFetch<SourceItem[]>('/api/sources'),
        apiFetch<AdapterItem[]>('/api/sources/adapters'),
        apiFetch<ScheduleInfo>('/api/sources/schedule'),
      ]);
      setItems(sources);
      setAdapters(adapterList);
      setSchedule(sched);
      setIntervalInput(sched.interval_minutes);
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

  const saveInterval = async () => {
    setSavingInterval(true);
    try {
      await apiFetch('/api/sources/schedule', {
        method: 'PUT',
        body: JSON.stringify({ interval_minutes: intervalInput }),
      });
      setSchedule((prev) => (prev ? { ...prev, interval_minutes: intervalInput } : prev));
      message.success(`自动采集间隔已改为每 ${intervalInput} 分钟，即时生效`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSavingInterval(false);
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

  const deleteSource = async (record: SourceItem) => {
    try {
      await apiFetch(`/api/sources/${record.id}`, { method: 'DELETE' });
      message.success(`已删除 ${record.display_name}`);
      void load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  const testCrawl = async () => {
    const adapter = form.getFieldValue('adapter');
    if (!adapter) {
      message.warning('请先选择采集平台');
      return;
    }
    const config = (form.getFieldValue('config') as object) || {};
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiFetch<TestResult>('/api/sources/test', {
        method: 'POST',
        body: JSON.stringify({ adapter, config }),
      });
      setTestResult(result);
      if (result.ok && result.items.length === 0) {
        message.warning('连接成功但未解析出任何公告，请检查配置');
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '测试失败');
    } finally {
      setTesting(false);
    }
  };

  const smartDetect = async () => {
    if (!smartUrl.trim()) {
      message.warning('请先粘贴招标网站的公告列表页网址');
      return;
    }
    setSmartDetecting(true);
    setSmartResult(null);
    setTestResult(null);
    try {
      const r = await apiFetch<SmartResult>('/api/sources/smart-suggest', {
        method: 'POST',
        body: JSON.stringify({ url: smartUrl.trim() }),
      });
      setSmartResult(r);
      if (r.ok) {
        // 识别成功：回填适配器 + 配置到表单（保存时用），并给中文名兜底
        form.setFieldsValue({ adapter: r.adapter, config: r.config ?? {} });
        if (!form.getFieldValue('display_name') && r.adapter_display_name) {
          form.setFieldsValue({ display_name: r.adapter_display_name });
        }
        message.success('识别成功，请核对预览后保存');
      } else if (r.error) {
        message.warning(r.error);
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '智能识别失败');
    } finally {
      setSmartDetecting(false);
    }
  };

  const openModal = (record: SourceItem | null) => {
    setEditing(record);
    setTestResult(null);
    setSmartResult(null);
    setSmartUrl('');
    setModalOpen(true);
    form.setFieldsValue(
      record
        ? {
            name: record.name,
            display_name: record.display_name,
            adapter: record.adapter,
            min_interval_seconds: record.min_interval_seconds,
            config: record.config ?? {},
          }
        : { name: '', display_name: '', adapter: undefined, min_interval_seconds: 3, config: {} },
    );
  };

  const onAdapterChange = () => {
    if (!editing) form.setFieldsValue({ config: {} }); // 换平台清空配置
  };

  const submit = async () => {
    const values = await form.validateFields();
    const config = (values.config as object) || {};
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
      width: 235,
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
          {record.announcement_count > 0 ? (
            <Tooltip title={`已采集 ${record.announcement_count} 条公告，为保数据完整性不可删除，可停用`}>
              <Button size="small" danger icon={<DeleteOutlined />} disabled />
            </Tooltip>
          ) : (
            <Popconfirm
              title={`删除数据源「${record.display_name}」？`}
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => deleteSource(record)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <AppLayout title="采集管理" subtitle="数据源配置、启停、手动触发与自动调度">
      {error ? <Alert type="warning" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      <Card className="compass-card" style={{ marginBottom: 16 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size="large" wrap align="center">
          <Space size={8}>
            <Typography.Text strong>自动采集间隔</Typography.Text>
            <InputNumber
              min={5}
              max={720}
              value={intervalInput}
              onChange={(v) => setIntervalInput(v ?? 30)}
              style={{ width: 90 }}
            />
            <Typography.Text>分钟</Typography.Text>
            <Button type="primary" loading={savingInterval} onClick={saveInterval}
              disabled={schedule?.interval_minutes === intervalInput}>
              保存
            </Button>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            上次自动采集：{formatDateTime(schedule?.last_auto_crawl_at)}（修改即时生效，最小 5 分钟以保持对源站的礼貌）
          </Typography.Text>
        </Space>
      </Card>
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
        title={editing ? `编辑数据源：${editing.display_name}` : '新增数据源'}
        open={modalOpen}
        onOk={submit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText={editing ? '保存' : '创建'}
        width={680}
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

          {/* 智能识别：新增数据源时的主流程——贴网址，AI 自动判定平台与采集方式 */}
          {!editing ? (
            <div
              style={{
                background: 'rgba(47,84,235,.04)',
                border: '1px solid rgba(47,84,235,.15)',
                borderRadius: 10,
                padding: 16,
                marginBottom: 16,
              }}
            >
              <Space size={8} style={{ marginBottom: 10 }}>
                <span className="ai-badge">
                  <RobotOutlined /> AI
                </span>
                <Typography.Text strong>智能识别</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  粘贴招标网站的公告列表页网址，自动判定采集方式并生成配置
                </Typography.Text>
              </Space>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="https://某招标网站/公告列表页"
                  value={smartUrl}
                  onChange={(e) => setSmartUrl(e.target.value)}
                  onPressEnter={smartDetect}
                />
                <Button
                  type="primary"
                  icon={<RobotOutlined />}
                  loading={smartDetecting}
                  onClick={smartDetect}
                >
                  智能识别
                </Button>
              </Space.Compact>
              {smartResult ? (
                smartResult.ok ? (
                  <Alert
                    style={{ marginTop: 12 }}
                    type="success"
                    showIcon
                    message={smartResult.notes || '识别成功'}
                    description={
                      <div style={{ fontSize: 12 }}>
                        <div style={{ marginBottom: 4 }}>
                          采集方式：{smartResult.adapter_display_name}　·　试采{' '}
                          {smartResult.items.length} 条
                          {smartResult.detail_preview
                            ? `　·　首条正文 ${smartResult.detail_preview.content_length} 字`
                            : ''}
                        </div>
                        {smartResult.items.slice(0, 3).map((it, i) => (
                          <div key={i} style={{ color: 'rgba(0,0,0,.55)' }}>
                            {it.publish_time ? `[${it.publish_time.slice(0, 10)}] ` : ''}
                            {it.title}
                          </div>
                        ))}
                      </div>
                    }
                  />
                ) : (
                  <Alert
                    style={{ marginTop: 12 }}
                    type="warning"
                    showIcon
                    message="未能自动识别"
                    description={smartResult.error || '请展开下方「高级设置」手动配置'}
                  />
                )
              ) : null}
            </div>
          ) : null}

          <Collapse
            ghost
            defaultActiveKey={editing ? ['adv'] : []}
            style={{ marginBottom: 8 }}
            items={[
              {
                key: 'adv',
                label: (
                  <Typography.Text type="secondary">
                    高级设置（手动选择适配器与选择器，覆盖智能识别结果）
                  </Typography.Text>
                ),
                children: (
                  <>
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
          <Form.Item name="min_interval_seconds" label="采集限速（每次请求最小间隔，秒）">
            <InputNumber min={1} max={60} style={{ width: 160 }} />
          </Form.Item>

          {watchedAdapter === 'ccgp' ? (
            <Form.Item
              name={['config', 'channels']}
              label="频道列表页地址"
              tooltip="要采集的公告频道列表页 URL，可填多个（回车分隔）"
            >
              <Select
                mode="tags"
                placeholder="如 https://www.ccgp.gov.cn/cggg/zygg/"
                tokenSeparators={[',', ' ']}
                open={false}
              />
            </Form.Item>
          ) : null}

          {watchedAdapter === 'jsggzy' ? (
            <>
              <Form.Item name={['config', 'categorynums']} label="采集类目">
                <Select mode="multiple" placeholder="选择要采集的公告类目" options={JSGGZY_CATEGORIES} />
              </Form.Item>
              <Form.Item name={['config', 'rows_per_category']} label="每类采集条数">
                <InputNumber min={5} max={100} style={{ width: 160 }} placeholder="20" />
              </Form.Item>
            </>
          ) : null}

          {watchedAdapter === 'generic' || watchedAdapter === 'generic_browser' ? (
            <>
              {watchedAdapter === 'generic' ? (
                <Form.Item
                  name={['config', 'list_url']}
                  label="公告列表页网址"
                  rules={[{ required: true, message: '请输入列表页网址' }]}
                >
                  <Input placeholder="https://某招标网站/公告列表页" />
                </Form.Item>
              ) : (
                <>
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message="动态渲染模式"
                    description="用真实浏览器执行页面 JS 后再采集，适用于列表由前端脚本生成的站点（httpx 拿不到数据时用）。渲染开销较大，速度比普通模式慢；带验证码/强反爬的站点可能仍无法采集。"
                  />
                  <Form.Item name={['config', 'list_url']} label="公告列表页网址" rules={[{ required: true, message: '请输入列表页网址' }]}>
                    <Input placeholder="https://某招标网站/公告列表页" />
                  </Form.Item>
                  <Form.Item name={['config', 'wait_selector']} label="等待元素（可选）" tooltip="渲染后等待此元素出现再采集，比默认等待更可靠，通常填公告条目选择器">
                    <Input placeholder="如 ul.news-list（留空则等页面加载完成）" />
                  </Form.Item>
                </>
              )}
              <Form.Item name={['config', 'item_selector']} label="公告条目选择器" tooltip="每条公告所在的元素（CSS 选择器）">
                <Input placeholder="如 ul.news-list li" />
              </Form.Item>
              <Space size={12} style={{ display: 'flex' }}>
                <Form.Item name={['config', 'link_selector']} label="链接选择器" style={{ flex: 1 }}>
                  <Input placeholder="默认 a" />
                </Form.Item>
                <Form.Item name={['config', 'date_selector']} label="日期选择器" style={{ flex: 1 }}>
                  <Input placeholder="可留空（自动识别）" />
                </Form.Item>
              </Space>
              <Form.Item name={['config', 'content_selector']} label="正文容器选择器">
                <Input placeholder="详情页正文所在元素" />
              </Form.Item>
              <Form.Item name={['config', 'region']} label="所属地区（可选）">
                <Input placeholder="如 江苏省" style={{ width: 200 }} />
              </Form.Item>
            </>
          ) : null}

          {!watchedAdapter ? (
            <Typography.Text type="secondary">请先在上方选择采集平台</Typography.Text>
          ) : null}

          <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 8 }}>
            <Space>
              <Button icon={<ThunderboltOutlined />} loading={testing} onClick={testCrawl}>
                测试采集
              </Button>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                保存前先试跑：抓列表前 5 条 + 首条正文，确认配置正确。
              </Typography.Text>
            </Space>
            {testResult ? (
              testResult.ok ? (
                <Alert
                  type={testResult.items.length ? 'success' : 'warning'}
                  showIcon
                  message={`解析出 ${testResult.items.length} 条公告${
                    testResult.detail_preview
                      ? `，首条正文 ${testResult.detail_preview.content_length} 字`
                      : ''
                  }`}
                  description={
                    <div style={{ fontSize: 12 }}>
                      {testResult.items.map((it, i) => (
                        <div key={i} style={{ marginBottom: 2 }}>
                          {it.publish_time ? `[${it.publish_time.slice(0, 10)}] ` : '[无日期] '}
                          {it.title}
                        </div>
                      ))}
                      {testResult.detail_preview ? (
                        <div className="evidence-quote" style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>
                          {testResult.detail_preview.content_excerpt.slice(0, 200)}…
                        </div>
                      ) : null}
                    </div>
                  }
                />
              ) : (
                <Alert type="error" showIcon message="测试失败" description={testResult.error} />
              )
            ) : null}
                  </Space>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Modal>
    </AppLayout>
  );
}
