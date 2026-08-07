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
    value: 'mimo',
    label: 'Xiaomi MiMo（小米）',
    base_url: 'https://api.xiaomimimo.com/v1',
    models: ['openai/mimo-v2.5-pro', 'openai/mimo-v2.5'],
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

  // 最新 state 镜像：失焦保存等异步路径读它，避免闭包旧值造成全量覆盖竞态
  const latest = useRef({ providers, sceneModels, fallback });
  latest.current = { providers, sceneModels, fallback };
  // 上次成功保存（或加载）的 payload 快照：内容没变就不重复 PUT，防审计日志刷屏
  const lastSaved = useRef('');

  /** 组装 PUT payload（接口是全量覆盖语义；未改动的密钥提交空串 = 保留已存密文） */
  const buildPayload = (
    nextProviders: ProviderRow[],
    nextScene: Record<string, SceneModel>,
    nextFallback: SceneModel | null
  ) => ({
    providers: nextProviders.map((p) => ({
      name: p.name,
      api_key: p.newKey ?? '',
      base_url: p.base_url,
    })),
    scene_models: Object.fromEntries(
      Object.entries(nextScene).filter(
        ([, value]) => value.provider.trim() && value.model.trim()
      )
    ),
    fallback: nextFallback?.provider.trim() && nextFallback.model.trim() ? nextFallback : null,
  });

  const load = () => {
    apiFetch<LlmConfig>('/api/admin/llm')
      .then((d) => {
        setProviders(d.providers);
        setSceneModels(d.scene_models);
        setFallback(d.fallback);
        setScenes(d.scenes);
        setUsage(d.usage_7d);
        lastSaved.current = JSON.stringify(buildPayload(d.providers, d.scene_models, d.fallback));
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  /** 立即持久化（传入下一刻的完整配置，避免闭包旧值）；内容与上次一致则跳过 */
  const persist = async (
    nextProviders: ProviderRow[],
    nextScene: Record<string, SceneModel>,
    nextFallback: SceneModel | null
  ): Promise<boolean> => {
    const serialized = JSON.stringify(buildPayload(nextProviders, nextScene, nextFallback));
    if (serialized === lastSaved.current) return true;
    try {
      await apiFetch('/api/admin/llm', { method: 'PUT', body: serialized });
      lastSaved.current = serialized;
      message.success({ content: '已保存', key: 'llm-save', duration: 1.2 });
      return true;
    } catch (e) {
      message.error((e as Error).message);
      return false;
    }
  };

  /** 有半填的场景行（选了供应商没填模型）时不落库，等补全再存——半截模型名一旦
   *  保存即刻生效，会让流水线调用不存在的模型并污染 LLM 连败计数 */
  const hasIncomplete = (s: Record<string, SceneModel>, f: SceneModel | null) =>
    [...Object.values(s), ...(f ? [f] : [])].some(
      (value) => !value.provider.trim() || !value.model.trim()
    );

  /** 场景映射输入框失焦时保存当前配置（用最新镜像，内容没变会被 persist 去重） */
  const saveCurrent = () => {
    const { providers: p, sceneModels: s, fallback: f } = latest.current;
    if (hasIncomplete(s, f)) return;
    void persist(p, s, f);
  };

  const openEdit = (p: ProviderRow | null) => {
    setEditing(p);
    editForm.setFieldsValue({
      preset: p ? (presetOf(p.name) ? p.name : CUSTOM) : PROVIDER_PRESETS[0].value,
      name: p?.name ?? '',
      api_key: '',
      // 编辑时保持已存值：留空的 base_url 有「走默认端点」语义，不能预填成预设 URL
      base_url: p ? p.base_url : PROVIDER_PRESETS[0].base_url,
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
    if (!editing && providers.some((p) => p.name === name)) {
      message.error(`供应商「${presetOf(name)?.label ?? name}」已存在，请直接编辑该行`);
      return;
    }
    const rest = providers.filter((p) => p.name !== name);
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
      // 先乐观更新本地列表（去掉已提交的明文 key），再 load() 刷新脱敏展示；
      // 否则刷新返回前的场景保存会用旧列表全量覆盖，把刚保存的编辑冲掉
      setProviders(next.map(({ newKey: _newKey, ...rest2 }) => rest2));
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
    if (await persist(next, nextScene, nextFallback)) {
      setProviders(next);
      setSceneModels(nextScene);
      setFallback(nextFallback);
      load();
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
              const preset = presetOf(p.name);
              const configured = sceneModels.default?.provider === p.name
                ? sceneModels.default.model
                : Object.values(sceneModels).find((item) => item.provider === p.name)?.model;
              setTestProvider(p.name);
              setTestModel(configured || preset?.models[0] || '');
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
    /** 更新本行并按需保存。保存用计算出的 next 值（setState 异步，不能读回 state）。 */
    const applyChange = (v: SceneModel | null, save: boolean) => {
      const nextScene = (() => {
        if (key === '__fallback__') return sceneModels;
        const next = { ...sceneModels };
        if (v) next[key] = v;
        else delete next[key];
        return next;
      })();
      const nextFallback = key === '__fallback__' ? v : fallback;
      if (key === '__fallback__') setFallback(v);
      else setSceneModels(nextScene);
      if (save && !hasIncomplete(nextScene, nextFallback)) {
        void persist(latest.current.providers, nextScene, nextFallback);
      }
    };
    return (
      <Space key={key} size={10} wrap>
        <Typography.Text style={{ width: 110, display: 'inline-block', fontSize: 13 }}>
          {label}
        </Typography.Text>
        <Select
          allowClear
          placeholder={key === 'default' ? '请选择默认供应商' : '继承默认'}
          style={{ width: 160 }}
          value={cur?.provider}
          options={providerOptions}
          onChange={(prov) => {
            if (!prov) {
              applyChange(null, true);
              return;
            }
            const suggested = presetOf(prov)?.models[0] ?? '';
            const model = (cur?.provider === prov ? cur.model : '') || suggested;
            // 带出了完整模型名（预设推荐）才保存；自定义供应商等模型填完再存
            applyChange({ provider: prov, model }, !!model.trim());
          }}
        />
        <AutoComplete
          placeholder="litellm 模型名，如 deepseek/deepseek-v4-flash"
          style={{ width: 300 }}
          value={cur?.model ?? ''}
          disabled={!cur?.provider}
          options={(presetOf(cur?.provider ?? '')?.models ?? []).map((m) => ({ value: m }))}
          // 键入只更新本地：半截模型名不落库（保存即生效，会打挂流水线调用）
          onChange={(v) => cur && applyChange({ ...cur, model: v }, false)}
          onSelect={(v: string) => cur && applyChange({ ...cur, model: v }, true)}
          onBlur={saveCurrent}
        />
        {cur?.provider && !cur.model.trim() ? (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            填写模型名后保存
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
              locale={{ emptyText: '尚未配置模型供应商，AI 功能暂不可用' }}
            />
          </Card>

          <Card className="compass-card" title="场景 → 模型映射">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              {Object.entries(scenes).map(([k, label]) => sceneRow(k, label))}
              {sceneRow('__fallback__', '备用模型')}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                未映射的场景使用「默认模型」；默认模型未设置时 AI 功能不可用。
                备用模型会在主模型调用失败时自动接管一次。
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
              extra={editing ? '名称是配置的引用标识，不可修改；需改名请删除后重建' : undefined}
              rules={[
                { required: true, message: '请输入名称' },
                { pattern: /^[a-z][a-z0-9_-]{1,31}$/, message: '小写字母开头，可含数字/中划线' },
              ]}
            >
              <Input maxLength={32} placeholder="如 my-gateway" disabled={!!editing} />
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
            extra={
              watchedPreset === 'mimo'
                ? 'MiMo：sk- 开头的按量 Key 使用默认地址；tp- 开头的 Token Plan Key 必须填写套餐页面提供的专属 Base URL'
                : 'DeepSeek 官方可留空；通义/智谱等填其兼容端点地址'
            }
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
        <Typography.Text strong>测试模型</Typography.Text>
        {presetOf(testProvider) ? (
          <>
            <Select
              style={{ width: '100%', marginTop: 8 }}
              value={testModel}
              onChange={setTestModel}
              options={presetOf(testProvider)!.models.map((model, index) => ({
                value: model,
                label: index === 0 ? `${model}（推荐）` : model,
              }))}
            />
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 6 }}>
              已自动选择推荐模型；也可以从该供应商支持的模型中切换。
            </Typography.Paragraph>
          </>
        ) : (
          <>
            <Input
              style={{ marginTop: 8 }}
              value={testModel}
              onChange={(event) => setTestModel(event.target.value)}
              placeholder="请输入供应商给出的模型 ID，如 moonshotai/kimi-k3-free"
            />
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 6 }}>
              直接填写供应商公布的模型 ID；系统会自动按 OpenAI 兼容协议调用。
            </Typography.Paragraph>
          </>
        )}
      </Modal>
    </AppLayout>
  );
}
