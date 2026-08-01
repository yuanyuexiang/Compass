'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  App,
  AutoComplete,
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

/** 常见供应商预设：选中自动带出 Base URL 与常用模型名（litellm 格式），免去手查文档 */
const PROVIDER_PRESETS: {
  value: string;
  label: string;
  base_url: string;
  models: string[];
}[] = [
  {
    value: 'deepseek',
    label: 'DeepSeek（深度求索）',
    base_url: '',
    models: ['deepseek/deepseek-v4-flash', 'deepseek/deepseek-chat', 'deepseek/deepseek-reasoner'],
  },
  {
    value: 'qwen',
    label: '通义千问（阿里云百炼）',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['openai/qwen-plus', 'openai/qwen-max', 'openai/qwen-turbo'],
  },
  {
    value: 'zhipu',
    label: '智谱 GLM',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    models: ['openai/glm-4-plus', 'openai/glm-4-air', 'openai/glm-4-flash'],
  },
  {
    value: 'moonshot',
    label: 'Kimi（月之暗面）',
    base_url: 'https://api.moonshot.cn/v1',
    models: ['openai/kimi-k2-0711-preview', 'openai/moonshot-v1-32k'],
  },
  {
    value: 'siliconflow',
    label: '硅基流动 SiliconFlow',
    base_url: 'https://api.siliconflow.cn/v1',
    models: ['openai/deepseek-ai/DeepSeek-V3', 'openai/Qwen/Qwen2.5-72B-Instruct'],
  },
  {
    value: 'openai',
    label: 'OpenAI',
    base_url: '',
    models: ['openai/gpt-4o-mini', 'openai/gpt-4o'],
  },
];

const CUSTOM = '__custom__';

function presetOf(name: string) {
  return PROVIDER_PRESETS.find((p) => p.value === name);
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
  const [editForm] = Form.useForm<{
    preset: string;
    name: string;
    api_key: string;
    base_url: string;
  }>();
  const watchedPreset = Form.useWatch('preset', editForm);

  const [testOpen, setTestOpen] = useState(false);
  const [testProvider, setTestProvider] = useState('');
  const [testModel, setTestModel] = useState('');
  const [testing, setTesting] = useState(false);

  // 自动保存控制：load() 引发的 state 变化不应触发自动保存
  const skipAutosave = useRef(true);
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = () => {
    apiFetch<LlmConfig>('/api/admin/llm')
      .then((d) => {
        skipAutosave.current = true;
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

  /** 立即持久化（供应商增删改用；传入下一刻的完整配置，避免闭包旧值） */
  const persist = async (
    nextProviders: ProviderRow[],
    nextScene: Record<string, SceneModel>,
    nextFallback: SceneModel | null
  ): Promise<boolean> => {
    const validScene = Object.fromEntries(
      Object.entries(nextScene).filter(
        ([, value]) => value.provider.trim() && value.model.trim()
      )
    );
    const validFallback = nextFallback?.provider.trim() && nextFallback.model.trim()
      ? nextFallback
      : null;
    try {
      await apiFetch('/api/admin/llm', {
        method: 'PUT',
        body: JSON.stringify({
          providers: nextProviders.map((p) => ({
            name: p.name,
            api_key: p.newKey ?? '',
            base_url: p.base_url,
          })),
          scene_models: validScene,
          fallback: validFallback,
        }),
      });
      message.success({ content: '已保存', key: 'llm-save', duration: 1.2 });
      return true;
    } catch (e) {
      message.error((e as Error).message);
      return false;
    }
  };

  // 场景映射/备用模型改动 → 600ms 防抖自动保存（供应商列表由弹窗流程即时保存）
  useEffect(() => {
    if (skipAutosave.current) {
      skipAutosave.current = false;
      return;
    }
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    const incomplete = [...Object.values(sceneModels), ...(fallback ? [fallback] : [])].some(
      (value) => !value.provider.trim() || !value.model.trim()
    );
    if (incomplete) return;
    autosaveTimer.current = setTimeout(() => {
      persist(providers, sceneModels, fallback);
    }, 600);
    return () => {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneModels, fallback]);

  const openEdit = (p: ProviderRow | null) => {
    setEditing(p);
    editForm.setFieldsValue({
      preset: p ? (presetOf(p.name) ? p.name : CUSTOM) : PROVIDER_PRESETS[0].value,
      name: p?.name ?? '',
      api_key: '',
      base_url: p?.base_url ?? (p ? '' : PROVIDER_PRESETS[0].base_url),
    });
    setEditOpen(true);
  };

  const onPresetChange = (v: string) => {
    const preset = presetOf(v);
    // 切换预设自动带出该家的 Base URL（自定义则清空待填）
    editForm.setFieldsValue({ base_url: preset?.base_url ?? '' });
  };

  const submitEdit = async () => {
    const v = await editForm.validateFields();
    const name = v.preset === CUSTOM ? v.name.trim() : v.preset;
    const rest = providers.filter((p) => p.name !== (editing?.name ?? name) && p.name !== name);
    const next = [
      ...rest,
      {
        name,
        base_url: v.base_url.trim(),
        api_key_masked: editing?.api_key_masked ?? '',
        newKey: v.api_key.trim() || undefined,
      },
    ];
    setSaving(true);
    const ok = await persist(next, sceneModels, fallback);
    setSaving(false);
    if (ok) {
      setEditOpen(false);
      load();
    }
  };

  const removeProvider = async (name: string) => {
    const next = providers.filter((p) => p.name !== name);
    // 引用该供应商的场景映射/备用一并清掉（后端也会兜底过滤）
    const nextScene = Object.fromEntries(
      Object.entries(sceneModels).filter(([, v]) => v.provider !== name)
    );
    const nextFallback = fallback?.provider === name ? null : fallback;
    if (await persist(next, nextScene, nextFallback)) load();
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

  const providerOptions = providers.map((p) => ({
    value: p.name,
    label: presetOf(p.name)?.label ?? p.name,
  }));

  const columns: ColumnsType<ProviderRow> = [
    {
      title: '名称',
      dataIndex: 'name',
      width: 200,
      render: (v: string) => <strong>{presetOf(v)?.label ?? v}</strong>,
    },
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
            disabled={!p.api_key_masked}
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
            title={`移除供应商「${presetOf(p.name)?.label ?? p.name}」？`}
            description="引用它的场景映射与备用配置将一并清除"
            onConfirm={() => removeProvider(p.name)}
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
          onChange={(prov) => {
            if (!prov) {
              setCur(null);
              return;
            }
            const suggested = presetOf(prov)?.models[0] ?? '';
            const currentModel = cur?.provider === prov ? cur.model : '';
            setCur({ provider: prov, model: currentModel || suggested });
          }}
        />
        <AutoComplete
          placeholder="litellm 模型名，如 deepseek/deepseek-v4-flash"
          style={{ width: 300 }}
          value={cur?.model ?? ''}
          disabled={!cur?.provider}
          options={(presetOf(cur?.provider ?? '')?.models ?? []).map((m) => ({ value: m }))}
          onChange={(v) => cur && setCur({ ...cur, model: v })}
        />
        {cur?.provider && !cur.model.trim() ? (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            填写模型名后自动保存
          </Typography.Text>
        ) : null}
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

        </Space>
      )}

      <Modal
        title={editing ? `编辑供应商：${editing.name}` : '新增供应商'}
        open={editOpen}
        onOk={submitEdit}
        onCancel={() => setEditOpen(false)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="preset" label="供应商" rules={[{ required: true, message: '请选择供应商' }]}>
            <Select
              disabled={!!editing}
              onChange={onPresetChange}
              options={[
                ...PROVIDER_PRESETS.map((p) => ({ value: p.value, label: p.label })),
                { value: CUSTOM, label: '自定义（其他 OpenAI 兼容服务）' },
              ]}
            />
          </Form.Item>
          {watchedPreset === CUSTOM ? (
            <Form.Item
              name="name"
              label="自定义名称（标识用，小写英文）"
              rules={[
                { required: true, message: '请输入名称' },
                { pattern: /^[a-z][a-z0-9_-]{1,31}$/, message: '小写字母开头，可含数字/中划线' },
              ]}
            >
              <Input maxLength={32} placeholder="如 my-gateway" />
            </Form.Item>
          ) : null}
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
        <Space.Compact style={{ width: '100%' }}>
          <Input style={{ width: 64 }} value="模型" disabled />
          <AutoComplete
            style={{ flex: 1 }}
            value={testModel}
            onChange={(v) => setTestModel(v)}
            options={(presetOf(testProvider)?.models ?? []).map((m) => ({ value: m }))}
            placeholder="deepseek/deepseek-v4-flash"
          />
        </Space.Compact>
      </Modal>
    </AppLayout>
  );
}
