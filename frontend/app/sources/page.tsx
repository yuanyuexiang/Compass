'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Row,
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
  status: 'pending' | 'active' | 'rejected';
  reject_reason: string | null;
  requested_by: string | null;
  min_interval_seconds: number;
  config: Record<string, unknown>;
  last_run_at: string | null;
  created_at: string | null;
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
  const { message, modal } = App.useApp();
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
  // 「高级设置」折叠面板展开状态：编辑时默认展开；校验失败时自动展开露出错误提示
  const [advOpen, setAdvOpen] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [sources, adapterList, sched] = await Promise.all([
        apiFetch<SourceItem[]>('/api/sources'),
        apiFetch<AdapterItem[]>('/api/sources/adapters'),
        apiFetch<ScheduleInfo>('/api/sources/schedule'),
      ]);
      setItems(sources);
      setSelectedId((current) => current ?? sources.find((item) => item.status !== 'pending')?.id ?? null);
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

  const approveSource = async (record: SourceItem) => {
    try {
      await apiFetch(`/api/sources/${record.id}/approve`, { method: 'POST' });
      message.success(`「${record.display_name}」已批准，开始参与采集`);
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const rejectSource = async (record: SourceItem) => {
    let reason = '';
    modal.confirm({
      title: `驳回申请「${record.display_name}」`,
      content: (
        <Input.TextArea
          rows={3}
          maxLength={500}
          placeholder="驳回理由（申请企业可见），例：非官方公开采购平台，暂不接入"
          onChange={(e) => {
            reason = e.target.value;
          }}
        />
      ),
      okText: '驳回',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        if (!reason.trim()) {
          message.warning('请填写驳回理由');
          return Promise.reject();
        }
        try {
          await apiFetch(`/api/sources/${record.id}/reject`, {
            method: 'POST',
            body: JSON.stringify({ reason: reason.trim() }),
          });
          message.success('已驳回');
          load();
        } catch (e) {
          message.error((e as Error).message);
          return Promise.reject();
        }
      },
    });
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
    setAdvOpen(record ? ['adv'] : []);
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
    let values: Awaited<ReturnType<typeof form.validateFields>>;
    try {
      values = await form.validateFields();
    } catch {
      // 必填项未过（多半是没选平台适配器）：自动展开高级设置让错误提示可见
      setAdvOpen(['adv']);
      message.warning('请先用「智能识别」自动配置，或在「高级设置」中选择平台适配器');
      return;
    }
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

  const pendingItems = items.filter((i) => i.status === 'pending');
  const listedItems = items.filter((i) => i.status !== 'pending');
  const selected = listedItems.find((item) => item.id === selectedId) ?? null;

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
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: SourceItem['status'], record) =>
        v === 'rejected' ? (
          <Tooltip title={record.reject_reason || ''}>
            <Tag color="red">已驳回</Tag>
          </Tooltip>
        ) : (
          <Tag color="green">生效</Tag>
        ),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (v: boolean, record) => (
        <Switch
          checked={v}
          disabled={record.status !== 'active'}
          onChange={(c) => toggleEnabled(record, c)}
        />
      ),
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
      {pendingItems.length > 0 ? (
        <Card
          className="compass-card"
          title={
            <Space size={8}>
              <span>待审批申请</span>
              <Tag color="gold">{pendingItems.length}</Tag>
            </Space>
          }
          style={{ marginBottom: 16 }}
        >
          <Table<SourceItem>
            rowKey="id"
            size="middle"
            pagination={false}
            dataSource={pendingItems}
            columns={[
              {
                title: '平台名称',
                dataIndex: 'display_name',
                render: (v: string, r) => (
                  <div>
                    <strong>{v}</strong>
                    <div style={{ fontSize: 12, color: 'rgba(0,0,0,.45)' }}>
                      {String(r.config?.url ?? '')}
                    </div>
                  </div>
                ),
              },
              {
                title: '申请企业',
                dataIndex: 'requested_by',
                width: 200,
                render: (v: string | null) => v ?? '-',
              },
              {
                title: '申请说明',
                key: 'note',
                ellipsis: true,
                render: (_, r) => String(r.config?.request_note ?? '') || '-',
              },
              {
                title: '申请时间',
                dataIndex: 'created_at',
                width: 150,
                render: (v: string | null) => formatDateTime(v),
              },
              {
                title: '操作',
                key: 'actions',
                width: 250,
                render: (_, r) => (
                  <Space>
                    <Button size="small" onClick={() => openModal(r)}>
                      配置并测试
                    </Button>
                    <Popconfirm
                      title={`批准「${r.display_name}」？通过后立即参与采集`}
                      okText="批准"
                      cancelText="取消"
                      onConfirm={() => approveSource(r)}
                    >
                      <Button size="small" type="primary">
                        通过
                      </Button>
                    </Popconfirm>
                    <Button size="small" danger onClick={() => rejectSource(r)}>
                      驳回
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            建议先「配置并测试」（贴网址 AI 识别 + 测试采集确认能出数据）再点通过；驳回需填写理由，申请企业可见。
          </Typography.Text>
        </Card>
      ) : null}

      <Row gutter={[16, 16]} align="top">
        <Col xs={24} lg={9} xl={8}>
          <Card
            className="compass-card opportunity-list-card"
            title={`数据源（${listedItems.length}）`}
            extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => openModal(null)}>新增</Button>}
          >
            <Button block icon={<CloudDownloadOutlined />} onClick={() => triggerCrawl()} style={{ marginBottom: 12 }}>全部采集</Button>
            <List<SourceItem>
              loading={loading}
              dataSource={listedItems}
              locale={{ emptyText: <Empty description="暂无数据源" /> }}
              renderItem={(item) => (
                <List.Item className={`opportunity-list-item${item.id === selectedId ? ' opportunity-list-item-active' : ''}`} onClick={() => setSelectedId(item.id)}>
                  <List.Item.Meta
                    title={<Typography.Text strong>{item.display_name}</Typography.Text>}
                    description={<Space direction="vertical" size={5}><Typography.Text type="secondary" style={{ fontSize: 12 }}>{item.name}</Typography.Text><Space wrap><Tag color={item.enabled ? 'green' : 'default'}>{item.enabled ? '运行中' : '已停用'}</Tag><Typography.Text type="secondary" style={{ fontSize: 12 }}>{item.announcement_count.toLocaleString()} 条公告</Typography.Text></Space></Space>}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={15} xl={16}>
          <Card className="compass-card opportunity-detail" title={selected?.display_name ?? '数据源详情'}>
            {selected ? <Space direction="vertical" size={20} style={{ width: '100%' }}>
              <Descriptions column={{ xs: 1, md: 2 }}>
                <Descriptions.Item label="唯一标识">{selected.name}</Descriptions.Item>
                <Descriptions.Item label="采集平台">{selected.adapter_display_name || selected.adapter}</Descriptions.Item>
                <Descriptions.Item label="运行状态"><Tag color={selected.enabled ? 'green' : 'default'}>{selected.enabled ? '已启用' : '已停用'}</Tag></Descriptions.Item>
                <Descriptions.Item label="累计公告">{selected.announcement_count.toLocaleString()}</Descriptions.Item>
                <Descriptions.Item label="上次采集">{formatDateTime(selected.last_run_at)}</Descriptions.Item>
                <Descriptions.Item label="限速">{selected.min_interval_seconds} 秒/请求</Descriptions.Item>
                <Descriptions.Item label="创建时间">{formatDateTime(selected.created_at)}</Descriptions.Item>
              </Descriptions>
              <Space wrap>
                <Button type="primary" icon={<ThunderboltOutlined />} disabled={!selected.enabled} onClick={() => triggerCrawl(selected)}>立即采集</Button>
                <Button onClick={() => openModal(selected)}>编辑配置</Button>
                <Space><Switch checked={selected.enabled} disabled={selected.status !== 'active'} onChange={(checked) => toggleEnabled(selected, checked)} /><Typography.Text>{selected.enabled ? '已启用' : '已停用'}</Typography.Text></Space>
                {selected.announcement_count === 0 ? <Popconfirm title={`删除数据源「${selected.display_name}」？`} onConfirm={() => deleteSource(selected)}><Button danger icon={<DeleteOutlined />}>删除</Button></Popconfirm> : null}
              </Space>
              <div><Typography.Text strong>采集配置</Typography.Text><pre className="opportunity-clean-text" style={{ marginTop: 10, padding: 14, background: '#fafbfd', borderRadius: 8 }}>{JSON.stringify(selected.config, null, 2)}</pre></div>
            </Space> : <Empty description="从左侧选择数据源" />}
          </Card>
        </Col>
      </Row>

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
            <Input placeholder="如 江苏公共资源·政府采购公告" maxLength={128} />
          </Form.Item>
          <Form.Item
            name="name"
            label="标识（唯一，用于日志与排查）"
            rules={[{ required: true, message: '请输入标识' }]}
          >
            <Input placeholder="如 jsggzy-zfcg" disabled={!!editing} maxLength={64} showCount />
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
            activeKey={advOpen}
            onChange={(keys) => setAdvOpen(typeof keys === 'string' ? [keys] : keys)}
            style={{ marginBottom: 8 }}
            items={[
              {
                key: 'adv',
                // 收起时也保持挂载：适配器/限速等字段必须始终注册进表单，
                // 否则校验被跳过、提交丢字段（历史缺陷：收起状态创建 → 422 adapter 缺失）
                forceRender: true,
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
          <Form.Item
            name="min_interval_seconds"
            label="采集限速（每次请求最小间隔，秒）"
            rules={[{ required: true, message: '请填写限速（1–60 秒）' }]}
          >
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
