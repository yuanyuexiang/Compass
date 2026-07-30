'use client';

import { useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ApiOutlined,
  DeleteOutlined,
  ExperimentOutlined,
  PlusOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';

interface ProviderRow {
  name: string;
  base_url: string;
  api_key_masked: string;
  /** 本次会话新输入的明文 key（仅提交用，接口永不回传） */
  newKey?: string;
}

interface SceneModel {
  provider: string;
  model: string;
}

interface LlmConfig {
  providers: { name: string; base_url: string; api_key_masked: string }[];
  scene_models: Record<string, SceneModel>;
  fallback: SceneModel | null;
  scenes: Record<string, string>;
  env_default: { model: string; configured: boolean };
  usage_7d: { model: string; calls: number; total_tokens: number }[];
}

export default function ModelsPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [providers, setProviders] = useState<ProviderRow[]>([]);
  const [sceneModels, setSceneModels] = useState<Record<string, SceneModel>>({});
  const [fallback, setFallback] = useState<SceneModel | null>(null);
  const [scenes, setScenes] = useState<Record<string, string>>({});
  const [envDefault, setEnvDefault] = useState<LlmConfig['env_default'] | null>(null);
  const [usage, setUsage] = useState<LlmConfig['usage_7d']>([]);

  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<ProviderRow | null>(null);
  const [editForm] = Form.useForm<{ name: string; api_key: string; base_url: string }>();

  const [testOpen, setTestOpen] = useState(false);
  const [testProvider, setTestProvider] = useState('');
  const [testModel, setTestModel] = useState('');
  const [testing, setTesting] = useState(false);

  const load = () => {
    apiFetch<LlmConfig>('/api/admin/llm')
      .then((d) => {
        setProviders(d.providers);
        setSceneModels(d.scene_models);
        setFallback(d.fallback);
        setScenes(d.scenes);
        setEnvDefault(d.env_default);
        setUsage(d.usage_7d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const openEdit = (p: ProviderRow | null) => {
    setEditing(p);
    editForm.setFieldsValue({ name: p?.name ?? '', api_key: '', base_url: p?.base_url ?? '' });
    setEditOpen(true);
  };

  const submitEdit = async () => {
    const v = await editForm.validateFields();
    const name = v.name.trim();
    setProviders((ps) => {
      const rest = ps.filter((p) => p.name !== (editing?.name ?? name) && p.name !== name);
      return [
        ...rest,
        {
          name,
          base_url: v.base_url.trim(),
          api_key_masked: v.api_key.trim() ? '（待保存）' : (editing?.api_key_masked ?? ''),
          newKey: v.api_key.trim() || editing?.newKey,
        },
      ];
    });
    setEditOpen(false);
    message.info('已加入待保存列表，点击「保存配置」生效');
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiFetch('/api/admin/llm', {
        method: 'PUT',
        body: JSON.stringify({
          providers: providers.map((p) => ({
            name: p.name,
            api_key: p.newKey ?? '',
            base_url: p.base_url,
          })),
          scene_models: sceneModels,
          fallback,
        }),
      });
      message.success('模型配置已保存，60 秒内全量生效（无需重启）');
      load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    if (!testModel.trim()) {
      message.warning('请填写要测试的模型名');
      return;
    }
    setTesting(true);
    try {
      const r = await apiFetch<{ ok: boolean; message: string }>('/api/admin/llm/test', {
        method: 'POST',
        body: JSON.stringify({ provider: testProvider, model: testModel.trim() }),
      });
      if (r.ok) message.success(r.message);
      else message.error(r.message);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setTesting(false);
    }
  };

  const providerOptions = providers.map((p) => ({ value: p.name, label: p.name }));

  const columns: ColumnsType<ProviderRow> = [
    { title: '名称', dataIndex: 'name', width: 140, render: (v) => <strong>{v}</strong> },
    {
      title: 'API Key',
      dataIndex: 'api_key_masked',
      width: 130,
      render: (v: string) => <Typography.Text code>{v || '未设置'}</Typography.Text>,
    },
    {
      title: 'Base URL（OpenAI 兼容端点，选填）',
      dataIndex: 'base_url',
      ellipsis: true,
      render: (v: string) => v || <Typography.Text type="secondary">默认</Typography.Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_, p) => (
        <Space>
          <Button
            size="small"
            icon={<ExperimentOutlined />}
            disabled={!p.api_key_masked || p.api_key_masked === '（待保存）'}
            onClick={() => {
              setTestProvider(p.name);
              setTestModel(sceneModels.default?.model ?? envDefault?.model ?? '');
              setTestOpen(true);
            }}
          >
            测试连接
          </Button>
          <Button size="small" onClick={() => openEdit(p)}>
            编辑
          </Button>
          <Popconfirm
            title={`移除供应商「${p.name}」？`}
            description="引用它的场景映射将失效（保存后生效）"
            onConfirm={() => setProviders((ps) => ps.filter((x) => x.name !== p.name))}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const sceneRow = (key: string, label: string) => {
    const cur = key === '__fallback__' ? fallback : sceneModels[key];
    const setCur = (v: SceneModel | null) => {
      if (key === '__fallback__') setFallback(v);
      else
        setSceneModels((m) => {
          const next = { ...m };
          if (v) next[key] = v;
          else delete next[key];
          return next;
        });
    };
    return (
      <Space key={key} size={10} wrap>
        <Typography.Text style={{ width: 110, display: 'inline-block', fontSize: 13 }}>
          {label}
        </Typography.Text>
        <Select
          allowClear
          placeholder={key === 'default' ? '未设置（走 .env）' : '继承默认'}
          style={{ width: 160 }}
          value={cur?.provider}
          options={providerOptions}
          onChange={(prov) =>
            prov ? setCur({ provider: prov, model: cur?.model ?? '' }) : setCur(null)
          }
        />
        <Input
          placeholder="litellm 模型名，如 deepseek/deepseek-v4-flash"
          style={{ width: 300 }}
          value={cur?.model ?? ''}
          disabled={!cur?.provider}
          onChange={(e) => cur && setCur({ ...cur, model: e.target.value })}
        />
      </Space>
    );
  };

  return (
    <AppLayout title="模型服务" subtitle="LLM 供应商与各场景模型配置（平台管理员），改动即时生效">
      {error ? <Alert type="warning" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {loading ? (
        <Card className="compass-card">
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card
            className="compass-card"
            title={
              <Space size={8}>
                <ApiOutlined style={{ color: '#2F54EB' }} />
                <span>模型供应商</span>
              </Space>
            }
            extra={
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit(null)}>
                新增供应商
              </Button>
            }
          >
            <Table<ProviderRow>
              rowKey="name"
              size="middle"
              columns={columns}
              dataSource={[...providers].sort((a, b) => a.name.localeCompare(b.name))}
              pagination={false}
              locale={{ emptyText: '未配置供应商时，全部调用走服务器 .env 里的 DeepSeek 配置' }}
            />
          </Card>

          <Card className="compass-card" title="场景 → 模型映射">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              {Object.entries(scenes).map(([k, label]) => sceneRow(k, label))}
              {sceneRow('__fallback__', '备用模型')}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                未映射的场景走「默认模型」；默认也未设置时走服务器 .env（当前：
                {envDefault?.model}
                {envDefault?.configured ? '' : '，key 未配置'}）。备用模型在主模型调用失败时自动接管一次。
              </Typography.Text>
            </Space>
          </Card>

          {usage.length ? (
            <Card className="compass-card" title="近 7 天各模型用量" size="small">
              <Table
                rowKey="model"
                size="small"
                pagination={false}
                columns={[
                  { title: '模型', dataIndex: 'model' },
                  { title: '调用次数', dataIndex: 'calls', width: 120 },
                  {
                    title: 'Token 总量',
                    dataIndex: 'total_tokens',
                    width: 140,
                    render: (v: number) => v.toLocaleString(),
                  },
                ]}
                dataSource={usage}
              />
            </Card>
          ) : null}

          <Button type="primary" size="large" icon={<SaveOutlined />} loading={saving} onClick={save}>
            保存配置
          </Button>
        </Space>
      )}

      <Modal
        title={editing ? `编辑供应商：${editing.name}` : '新增供应商'}
        open={editOpen}
        onOk={submitEdit}
        onCancel={() => setEditOpen(false)}
        okText="确定"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="name"
            label="名称（标识用，如 deepseek / qwen / zhipu）"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input maxLength={32} disabled={!!editing} />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            extra={editing ? '留空表示保持已存密钥不变' : undefined}
            rules={editing ? [] : [{ required: true, message: '请输入 API Key' }]}
          >
            <Input.Password placeholder={editing ? '（不修改则留空）' : 'sk-...'} />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="Base URL（选填，OpenAI 兼容端点）"
            extra="DeepSeek 官方可留空；通义/智谱等填其兼容端点地址"
          >
            <Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`测试连接：${testProvider}`}
        open={testOpen}
        onOk={runTest}
        onCancel={() => setTestOpen(false)}
        confirmLoading={testing}
        okText="发起测试"
        cancelText="关闭"
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          将用该供应商已保存的密钥发起一次最小调用，实测连通性、密钥有效性与余额状态。
        </Typography.Paragraph>
        <Input
          addonBefore="模型"
          value={testModel}
          onChange={(e) => setTestModel(e.target.value)}
          placeholder="deepseek/deepseek-v4-flash"
        />
      </Modal>
    </AppLayout>
  );
}
