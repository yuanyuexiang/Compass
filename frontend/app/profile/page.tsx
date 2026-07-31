'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Badge,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Row,
  Select,
  Skeleton,
  Space,
  Tag,
  Tabs,
  Typography,
} from 'antd';
import {
  EditOutlined,
  FileAddOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  GlobalOutlined,
  PlusOutlined,
  RobotOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import ProfileEvidencePanel from '@/components/ProfileEvidencePanel';
import { apiFetch } from '@/lib/api';
import { formatDateTime } from '@/lib/labels';
import type { ProfileData, ProfileFactItem, ProfileMaterialItem, ProfileSuggestResult } from '@/lib/types';

const CONFIDENCE_TAG: Record<string, { color: string; label: string }> = {
  high: { color: 'green', label: '可信度高' },
  medium: { color: 'orange', label: '可信度中' },
  low: { color: 'red', label: '可信度低' },
};

// 标签输入的分隔符：顿号/逗号/分号粘贴整段自动切分成多个标签
const TAG_SEPARATORS = [',', '，', '、', ';', '；'];
const SEP_RE = /[,，、;；]/;

const PROVINCE_OPTIONS = [
  '全国', '北京市', '天津市', '河北省', '山西省', '内蒙古自治区', '辽宁省', '吉林省',
  '黑龙江省', '上海市', '江苏省', '浙江省', '安徽省', '福建省', '江西省', '山东省',
  '河南省', '湖北省', '湖南省', '广东省', '广西壮族自治区', '海南省', '重庆市',
  '四川省', '贵州省', '云南省', '西藏自治区', '陕西省', '甘肃省', '青海省',
  '宁夏回族自治区', '新疆维吾尔自治区',
];

const INDUSTRY_OPTIONS = [
  '政务', '教育', '医疗', '金融', '交通', '能源', '制造', '水利', '环保', '农业',
  '文旅', '司法', '公安', '应急', '电信', '科研院所', '园区物业', '军队',
];

const PRODUCT_OPTIONS = [
  '软件开发', '硬件开发', '系统集成', '智能化系统', '安防监控系统', '综合布线',
  '机房工程', '弱电工程', '视频会议系统', '网络设备', '服务器与存储', '大数据平台',
  '人工智能应用', '物联网设备', 'LED 显示屏', '广播系统', '楼宇自控',
];

const SERVICE_OPTIONS = [
  '软件开发', '系统集成', '信息化运维', '智能化工程', '装饰装修工程', '展厅设计施工',
  '展览展示服务', '广告设计制作', '数据治理', '网络安全服务', '咨询设计',
  '设备维保', '机电安装',
];

const CERT_OPTIONS = [
  'ISO9001', 'ISO14001', 'ISO20000', 'ISO27001', 'CMMI3', 'CMMI5',
  'ITSS 运维能力成熟度', '高新技术企业', '安全生产许可证',
  '建筑装修装饰工程专业承包一级', '建筑装修装饰工程专业承包二级',
  '电子与智能化工程专业承包一级', '电子与智能化工程专业承包二级',
  '建筑机电安装工程专业承包三级', '信息系统建设和服务能力评估 CS2',
];

const BRAND_OPTIONS = [
  '华为', '海康威视', '大华', '新华三', '锐捷', '浪潮', '联想', '中兴',
  '戴尔', '施耐德', '西门子', '霍尼韦尔',
];

const TAG_FIELDS: {
  name: keyof ProfileData;
  label: string;
  placeholder: string;
  options: string[];
}[] = [
  { name: 'products', label: '主要产品', placeholder: '下拉选择或输入，可整段粘贴自动切分', options: PRODUCT_OPTIONS },
  { name: 'services', label: '主要服务', placeholder: '下拉选择或输入，可整段粘贴自动切分', options: SERVICE_OPTIONS },
  { name: 'industries', label: '覆盖行业', placeholder: '下拉选择，也可输入自定义行业', options: INDUSTRY_OPTIONS },
  { name: 'regions', label: '业务区域', placeholder: '下拉选省份，也可输入到市（如：南京市）', options: PROVINCE_OPTIONS },
  { name: 'certifications', label: '资质证书', placeholder: '下拉选择常见资质，也可输入其他', options: CERT_OPTIONS },
  { name: 'brands', label: '代理品牌', placeholder: '下拉选择或输入其他品牌', options: BRAND_OPTIONS },
];

/** 把「软件开发、硬件开发」这类连写标签切分成独立标签（兼容存量脏数据与整段粘贴） */
function splitTags(list?: string[]): string[] {
  const out: string[] = [];
  for (const v of list ?? []) {
    for (const part of String(v).split(SEP_RE)) {
      const t = part.trim();
      if (t && !out.includes(t)) out.push(t);
    }
  }
  return out;
}

/** 画像完成度：9 个内容项的填写比例 + 缺项清单（画像越完整，AI 匹配越准） */
function profileCompleteness(d: ProfileData): { percent: number; missing: string[] } {
  const checks: [string, boolean][] = [
    ['企业简介', !!d.description],
    ['主要产品', !!d.products?.length],
    ['主要服务', !!d.services?.length],
    ['覆盖行业', !!d.industries?.length],
    ['业务区域', !!d.regions?.length],
    ['资质证书', !!d.certifications?.length],
    ['代理品牌', !!d.brands?.length],
    ['典型案例', !!d.cases_text],
    ['推荐过滤', !!d.filter?.regions?.length || d.filter?.min_budget != null],
  ];
  const done = checks.filter(([, ok]) => ok).length;
  return {
    percent: Math.round((done / checks.length) * 100),
    missing: checks.filter(([, ok]) => !ok).map(([label]) => label),
  };
}

function isProfileEmpty(d: ProfileData): boolean {
  return (
    !d.description &&
    !d.cases_text &&
    [d.products, d.services, d.industries, d.regions, d.certifications, d.brands].every(
      (l) => !l?.length
    ) &&
    !d.filter?.regions?.length &&
    d.filter?.min_budget == null
  );
}

const fmtList = (l?: string[]) => (l?.length ? l.join('、') : '不限');
const fmtBudget = (v?: number | null) =>
  v == null ? '不限' : v >= 10000 ? `${v / 10000} 万元` : `${v} 元`;

/** 保存前的变更清单：影响匹配范围的过滤条件逐项列出，其余字段汇总 */
function computeDiffs(oldD: ProfileData | null, newD: ProfileData): string[] {
  const out: string[] = [];
  const oldRegions = fmtList(oldD?.filter?.regions);
  const newRegions = fmtList(newD.filter?.regions);
  if (oldRegions !== newRegions) out.push(`仅关注地区：${oldRegions} → ${newRegions}`);
  const oldBudget = fmtBudget(oldD?.filter?.min_budget);
  const newBudget = fmtBudget(newD.filter?.min_budget);
  if (oldBudget !== newBudget) out.push(`最低预算：${oldBudget} → ${newBudget}`);
  const OTHER: [keyof ProfileData, string][] = [
    ['description', '企业简介'],
    ['products', '主要产品'],
    ['services', '主要服务'],
    ['industries', '覆盖行业'],
    ['regions', '业务区域'],
    ['certifications', '资质证书'],
    ['brands', '代理品牌'],
    ['cases_text', '典型案例'],
  ];
  const changed = OTHER.filter(
    ([k]) => JSON.stringify(oldD?.[k] ?? null) !== JSON.stringify(newD[k] ?? null)
  ).map(([, label]) => label);
  if (changed.length) out.push(`内容更新：${changed.join('、')}`);
  return out;
}

/** AI 成果预览行：字段级「当前 vs 建议」+ 应用方式 */
interface SuggestRow {
  key: string;
  label: string;
  kind: 'tags' | 'text';
  current: string[] | string;
  suggested: string[] | string;
  action: 'merge' | 'replace' | 'ignore';
}

const SUGGEST_FIELD_DEFS: { key: keyof ProfileData; label: string; kind: 'tags' | 'text' }[] = [
  { key: 'description', label: '企业简介', kind: 'text' },
  { key: 'products', label: '主要产品', kind: 'tags' },
  { key: 'services', label: '主要服务', kind: 'tags' },
  { key: 'industries', label: '覆盖行业', kind: 'tags' },
  { key: 'regions', label: '业务区域', kind: 'tags' },
  { key: 'certifications', label: '资质证书', kind: 'tags' },
  { key: 'brands', label: '代理品牌', kind: 'tags' },
  { key: 'cases_text', label: '典型案例', kind: 'text' },
];

/** 从 AI 草稿构建预览行：只含 AI 有产出的字段（没产出的字段不出现、绝不清空现值） */
function buildSuggestRows(current: Partial<ProfileData>, draft: Partial<ProfileData>): SuggestRow[] {
  const rows: SuggestRow[] = [];
  for (const def of SUGGEST_FIELD_DEFS) {
    const raw = draft[def.key];
    const suggested = def.kind === 'tags' ? splitTags(raw as string[] | undefined) : String(raw ?? '').trim();
    const empty = def.kind === 'tags' ? !(suggested as string[]).length : !suggested;
    if (empty) continue;
    const cur = def.kind === 'tags'
      ? splitTags(current[def.key] as string[] | undefined)
      : String(current[def.key] ?? '').trim();
    const curEmpty = def.kind === 'tags' ? !(cur as string[]).length : !cur;
    rows.push({
      key: def.key,
      label: def.label,
      kind: def.kind,
      current: cur,
      suggested,
      // 默认策略：当前为空→填入(replace)；标签类都有→合并；文本类已有内容→忽略（防覆盖手写）
      action: curEmpty ? 'replace' : def.kind === 'tags' ? 'merge' : 'ignore',
    });
  }
  return rows;
}

function applySuggestRows(rows: SuggestRow[]): Partial<ProfileData> {
  const out: Record<string, unknown> = {};
  for (const r of rows) {
    if (r.action === 'ignore') continue;
    if (r.kind === 'tags') {
      const cur = r.current as string[];
      const sug = r.suggested as string[];
      out[r.key] = r.action === 'merge' ? [...new Set([...cur, ...sug])] : sug;
    } else {
      out[r.key] = r.suggested;
    }
  }
  return out as Partial<ProfileData>;
}

function normalizeProfile<T extends Partial<ProfileData>>(d: T): T {
  return {
    ...d,
    products: splitTags(d.products),
    services: splitTags(d.services),
    industries: splitTags(d.industries),
    regions: splitTags(d.regions),
    certifications: splitTags(d.certifications),
    brands: splitTags(d.brands),
    filter: { ...d.filter, regions: splitTags(d.filter?.regions) },
  };
}

export default function ProfilePage() {
  const { message } = App.useApp();
  const [form] = Form.useForm<ProfileData>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // AI 生成画像：输入企业名 → 联网整理草稿 → 成果弹窗逐字段确认后应用，用户保存才生效
  const [aiName, setAiName] = useState('');
  const [suggesting, setSuggesting] = useState(false);
  const [suggestMeta, setSuggestMeta] = useState<Omit<ProfileSuggestResult, 'draft'> | null>(null);
  const [suggestRows, setSuggestRows] = useState<SuggestRow[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);

  const applySuggest = () => {
    const patch = applySuggestRows(suggestRows);
    form.setFieldsValue(patch);
    setSuggestOpen(false);
    const applied = suggestRows.filter((r) => r.action !== 'ignore').length;
    message.success(`已应用 ${applied} 个字段的 AI 建议，核对后点「保存并生效」`);
  };

  const runSuggest = async () => {
    const name = aiName.trim();
    if (!name) {
      message.warning('请先输入企业名称');
      return;
    }
    setSuggesting(true);
    try {
      const r = await apiFetch<ProfileSuggestResult>('/api/profile/suggest', {
        method: 'POST',
        body: JSON.stringify({ name }),
      });
      // name 为注册企业名（只读权威字段），不接受 AI 草稿覆盖
      const { name: _draftName, ...draft } = r.draft;
      setSuggestMeta({
        sources: r.sources,
        source_groups: r.source_groups,
        confidence: r.confidence,
        note: r.note,
      });
      // 不直接改表单：弹「AI 画像成果」逐字段确认（当前 vs 建议，合并/替换/忽略）
      const rows = buildSuggestRows(form.getFieldsValue(), draft);
      if (!rows.length) {
        message.info('AI 未产出可用的画像内容，请参考来源手动填写');
        return;
      }
      setSuggestRows(rows);
      setSuggestOpen(true);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSuggesting(false);
    }
  };

  // 查看态为默认：画像是驱动匹配的"合同"，编辑是显式动作，保存即生效并触发重评估
  const [mode, setMode] = useState<'view' | 'edit'>('view');
  const [profileData, setProfileData] = useState<ProfileData | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingPayload, setPendingPayload] = useState<ProfileData | null>(null);
  const [diffs, setDiffs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<'profile' | 'review' | 'materials'>('profile');
  const [improveOpen, setImproveOpen] = useState(false);
  const [evidenceCounts, setEvidenceCounts] = useState({ pending: 0, materials: 0 });
  const handleEvidenceCounts = useCallback(
    (counts: { pending: number; materials: number }) => setEvidenceCounts(counts),
    []
  );

  useEffect(() => {
    apiFetch<ProfileData>('/api/profile')
      .then((data) => {
        const normalized = normalizeProfile(data);
        setProfileData(normalized);
        form.setFieldsValue(normalized);
        // 全新租户（画像还是空的）直接进编辑态，老租户默认查看态
        if (isProfileEmpty(normalized)) setMode('edit');
        // AI 生成画像默认按注册企业名联网检索（可改，比如想按品牌名搜）
        setAiName((prev) => prev || data.name || '');
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [form]);

  useEffect(() => {
    Promise.all([
      apiFetch<ProfileMaterialItem[]>('/api/profile/materials'),
      apiFetch<ProfileFactItem[]>('/api/profile/facts?status=pending'),
    ]).then(([materials, facts]) => {
      setEvidenceCounts({ materials: materials.length, pending: facts.length });
    }).catch(() => {
      // 主画像仍可正常使用；资料区打开时会再次加载并显示具体错误。
    });
  }, []);

  const enterEdit = () => {
    if (profileData) form.setFieldsValue(profileData);
    setActiveTab('profile');
    setMode('edit');
  };

  const chooseImproveMethod = (method: 'upload' | 'public' | 'manual') => {
    setImproveOpen(false);
    if (method === 'upload') {
      setActiveTab('materials');
      return;
    }
    enterEdit();
    if (method === 'public') window.setTimeout(() => document.getElementById('ai-profile-entry')?.scrollIntoView({ behavior: 'smooth' }), 50);
  };

  const cancelEdit = () => {
    if (profileData) form.setFieldsValue(profileData);
    setSuggestMeta(null);
    setMode('view');
  };

  // 点「保存并生效」：先算关键变更给用户确认，确认后才真正提交
  const onFinish = async (values: ProfileData) => {
    const payload: ProfileData = normalizeProfile({
      name: values.name ?? '',
      description: values.description ?? '',
      products: values.products ?? [],
      services: values.services ?? [],
      industries: values.industries ?? [],
      regions: values.regions ?? [],
      certifications: values.certifications ?? [],
      brands: values.brands ?? [],
      cases_text: values.cases_text ?? '',
      filter: {
        regions: values.filter?.regions ?? [],
        min_budget: values.filter?.min_budget ?? null,
      },
    });
    const changes = computeDiffs(profileData, payload);
    if (changes.length === 0) {
      message.info('画像内容没有变化');
      setMode('view');
      return;
    }
    setPendingPayload(payload);
    setDiffs(changes);
    setConfirmOpen(true);
  };

  const REMATCH_TIPS: Record<string, string> = {
    queued: '画像已生效，正在按新画像重新评估近 7 天商机，稍后到工作台查看',
    cooldown: '画像已生效（10 分钟内已触发过重新评估，本次不再重复）',
    unchanged: '画像已保存，内容无实质变化',
    queue_failed: '画像已生效，但重新评估任务提交失败，可稍后再保存一次触发',
  };

  const confirmSave = async () => {
    if (!pendingPayload) return;
    setSaving(true);
    try {
      const r = await apiFetch<{ ok: boolean; rematch?: string }>('/api/profile', {
        method: 'PUT',
        body: JSON.stringify(pendingPayload),
      });
      message.success(REMATCH_TIPS[r.rematch ?? ''] ?? '企业画像已保存');
      const merged = { ...pendingPayload, updated_at: new Date().toISOString() };
      setProfileData(merged);
      form.setFieldsValue(merged);
      setConfirmOpen(false);
      setSuggestMeta(null);
      setMode('view');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppLayout title="企业能力画像" subtitle="画像越完整，AI 匹配越精准">
      {error ? (
        <Alert
          type="warning"
          showIcon
          message="画像加载失败，可直接填写后保存"
          description={error}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {loading ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card className="compass-card">
            <Skeleton active paragraph={{ rows: 3 }} />
          </Card>
          <Card className="compass-card">
            <Skeleton active paragraph={{ rows: 4 }} />
          </Card>
        </Space>
      ) : null}
      {!loading && profileData ? (
        <Card className="compass-card" style={{ marginBottom: 16 }}>
          <Row gutter={[20, 16]} align="middle" justify="space-between">
            <Col flex="auto">
              <Space direction="vertical" size={7}>
                <Space size={10} wrap>
                  <Typography.Title level={4} style={{ margin: 0 }}>{profileData.name || '企业能力画像'}</Typography.Title>
                  <Tag color="green">当前生效</Tag>
                </Space>
                <Space size={14} wrap>
                  <Typography.Text type="secondary">
                    画像完成度 {profileCompleteness(profileData).percent}%
                  </Typography.Text>
                  <Progress
                    percent={profileCompleteness(profileData).percent}
                    showInfo={false}
                    size="small"
                    style={{ width: 120, margin: 0 }}
                  />
                  <Typography.Text type="secondary">{evidenceCounts.materials} 份企业材料</Typography.Text>
                  {profileData.updated_at ? (
                    <Typography.Text type="secondary">更新于 {formatDateTime(profileData.updated_at)}</Typography.Text>
                  ) : null}
                </Space>
              </Space>
            </Col>
            <Col>
              <Space wrap>
                <Button icon={<EditOutlined />} onClick={enterEdit}>直接编辑</Button>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setImproveOpen(true)}>完善画像</Button>
              </Space>
            </Col>
          </Row>
          {evidenceCounts.pending > 0 ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 16 }}
              message={`AI 已从企业材料中发现 ${evidenceCounts.pending} 条能力信息，确认后才会写入画像`}
              action={<Button size="small" type="link" onClick={() => setActiveTab('review')}>立即核对</Button>}
            />
          ) : null}
        </Card>
      ) : null}
      {!loading ? (
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as typeof activeTab)}
          style={{ marginBottom: 16 }}
          items={[
            { key: 'profile', label: '当前画像', icon: <FileSearchOutlined /> },
            {
              key: 'review',
              label: <Space size={6}>待确认建议{evidenceCounts.pending ? <Badge count={evidenceCounts.pending} size="small" /> : null}</Space>,
              icon: <RobotOutlined />,
            },
            { key: 'materials', label: `企业资料库${evidenceCounts.materials ? `（${evidenceCounts.materials}）` : ''}`, icon: <FolderOpenOutlined /> },
          ]}
        />
      ) : null}
      {!loading && activeTab !== 'profile' ? (
        <ProfileEvidencePanel
          section={activeTab === 'review' ? 'review' : 'materials'}
          onCountsChange={handleEvidenceCounts}
          onProfileChanged={async () => {
            const data = normalizeProfile(await apiFetch<ProfileData>('/api/profile'));
            setProfileData(data);
            form.setFieldsValue(data);
          }}
        />
      ) : null}
      {/* 查看态：当前生效画像的只读展示 */}
      {!loading && activeTab === 'profile' && mode === 'view' && profileData ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card
            className="compass-card"
            title="基本信息"
            extra={
              <Button icon={<EditOutlined />} onClick={enterEdit}>编辑画像</Button>
            }
          >
            <Typography.Title level={5} style={{ marginTop: 0 }}>
              {profileData.name}
            </Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              当前生效版本
              {profileData.updated_at ? ` · 更新于 ${formatDateTime(profileData.updated_at)}` : ''}
            </Typography.Text>
            <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
              {profileData.description || <Typography.Text type="secondary">未填写企业简介</Typography.Text>}
            </Typography.Paragraph>
            {(() => {
              const { percent, missing } = profileCompleteness(profileData);
              return percent < 100 ? (
                <div style={{ marginTop: 14, maxWidth: 520 }}>
                  <Space size={10} align="center" style={{ width: '100%' }}>
                    <Typography.Text type="secondary" style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                      画像完成度
                    </Typography.Text>
                    <div style={{ width: 180 }}>
                      <Progress percent={percent} size="small" />
                    </div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      还差：{missing.join('、')}——越完整，AI 匹配越准
                    </Typography.Text>
                  </Space>
                </div>
              ) : null;
            })()}
          </Card>

          <Card className="compass-card" title="能力标签">
            <Row gutter={[24, 16]}>
              {TAG_FIELDS.map((f) => (
                <Col xs={24} md={12} key={f.name}>
                  <Typography.Text type="secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>
                    {f.label}
                  </Typography.Text>
                  {(profileData[f.name] as string[])?.length ? (
                    <Space size={[6, 6]} wrap>
                      {(profileData[f.name] as string[]).map((t) => (
                        <Tag key={t} color="blue">{t}</Tag>
                      ))}
                    </Space>
                  ) : (
                    <Typography.Text type="secondary" style={{ fontSize: 13 }}>未填写</Typography.Text>
                  )}
                </Col>
              ))}
            </Row>
          </Card>

          <Card className="compass-card" title="推荐过滤（决定匹配范围）">
            <Space size="large" wrap>
              <span>
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>仅关注地区：</Typography.Text>
                <Typography.Text strong>{fmtList(profileData.filter?.regions)}</Typography.Text>
              </span>
              <span>
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>最低预算：</Typography.Text>
                <Typography.Text strong>{fmtBudget(profileData.filter?.min_budget)}</Typography.Text>
              </span>
            </Space>
          </Card>

          <Card className="compass-card" title="典型案例">
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
              {profileData.cases_text || <Typography.Text type="secondary">未填写</Typography.Text>}
            </Typography.Paragraph>
          </Card>
        </Space>
      ) : null}

      {/* 编辑态（Form 始终挂载避免 useForm 未连接警告；查看态下隐藏） */}
      <div style={{ display: loading || activeTab !== 'profile' || mode === 'view' ? 'none' : undefined }}>
        <Form<ProfileData> form={form} layout="vertical" onFinish={onFinish}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card id="ai-profile-entry" className="compass-card" title={<span><RobotOutlined style={{ color: '#2F54EB', marginRight: 6 }} />从公开信息补充画像</span>}>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="输入企业全称，AI 自动联网整理画像草稿"
                  value={aiName}
                  onChange={(e) => setAiName(e.target.value)}
                  onPressEnter={runSuggest}
                  allowClear
                />
                <Button type="primary" icon={<RobotOutlined />} loading={suggesting} onClick={runSuggest}>
                  AI 生成
                </Button>
              </Space.Compact>
              {suggestMeta ? (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 12 }}
                  message={
                    <Space size={8} wrap>
                      <Tag color={CONFIDENCE_TAG[suggestMeta.confidence]?.color ?? 'blue'}>
                        {CONFIDENCE_TAG[suggestMeta.confidence]?.label ?? suggestMeta.confidence}
                      </Tag>
                      <span>{suggestMeta.note}</span>
                    </Space>
                  }
                  description={
                    suggestMeta.source_groups?.length ? (
                      <Space direction="vertical" size={4} style={{ width: '100%' }}>
                        {suggestMeta.source_groups.map((g) => (
                          <Space key={g.label} size={[8, 4]} wrap>
                            <Tag style={{ fontSize: 11 }}>{g.label}</Tag>
                            {g.items.map((it, i) =>
                              it.link ? (
                                <a
                                  key={`${g.label}-${i}`}
                                  href={it.link}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{ fontSize: 12, maxWidth: 320, display: 'inline-block' }}
                                  className="suggest-source-link"
                                  title={it.title ?? it.link}
                                >
                                  {(it.title ?? it.link).length > 32
                                    ? `${(it.title ?? it.link).slice(0, 32)}…`
                                    : it.title ?? it.link}
                                </a>
                              ) : null
                            )}
                          </Space>
                        ))}
                      </Space>
                    ) : suggestMeta.sources.length ? (
                      <Space size={[8, 4]} wrap>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          来源：
                        </Typography.Text>
                        {suggestMeta.sources.map((s, i) => (
                          <a key={s} href={s} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
                            链接{i + 1}
                          </a>
                        ))}
                      </Space>
                    ) : null
                  }
                />
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 10 }}>
                  草稿会填入下方表单，你可修改后再保存；未搜到的字段留空，需手动补充。「仅关注地区/最低预算」属经营决策，请自行设置。
                </Typography.Text>
              )}
            </Card>

            <Card className="compass-card" title="基本信息">
              <Row gutter={24}>
                <Col xs={24} md={12}>
                  <Form.Item
                    name="name"
                    label="企业名称"
                    extra="即注册申请时的企业名称，全平台统一展示；如需变更请联系平台管理员"
                  >
                    <Input disabled />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="description" label="企业简介" style={{ marginBottom: 0 }}>
                <Input.TextArea rows={3} placeholder="企业主营业务、核心能力简述" />
              </Form.Item>
            </Card>

            <Card className="compass-card" title="能力标签">
              <Row gutter={24}>
                {TAG_FIELDS.map((f) => (
                  <Col xs={24} md={12} key={f.name}>
                    <Form.Item name={f.name} label={f.label}>
                      <Select
                        mode="tags"
                        placeholder={f.placeholder}
                        options={f.options.map((v) => ({ value: v, label: v }))}
                        tokenSeparators={TAG_SEPARATORS}
                        allowClear
                      />
                    </Form.Item>
                  </Col>
                ))}
              </Row>
            </Card>

            <Card className="compass-card" title="典型案例">
              <Form.Item name="cases_text" style={{ marginBottom: 0 }}>
                <Input.TextArea rows={4} placeholder="过往项目案例描述，用于 AI 匹配参考" />
              </Form.Item>
            </Card>

            <Card className="compass-card" title="推荐过滤条件">
              <Row gutter={24}>
                <Col xs={24} md={12}>
                  <Form.Item
                    name={['filter', 'regions']}
                    label="仅关注地区"
                    extra="推荐与商机查询只看这些省份的项目；选「全国」或留空表示不限"
                  >
                    <Select
                      mode="multiple"
                      placeholder="留空表示不限地区"
                      options={PROVINCE_OPTIONS.map((v) => ({ value: v, label: v }))}
                      allowClear
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name={['filter', 'min_budget']} label="最低预算（元）">
                    <InputNumber style={{ width: '100%' }} min={0} placeholder="留空表示不限预算" />
                  </Form.Item>
                </Col>
              </Row>
            </Card>

            <Space>
              <Button type="primary" htmlType="submit" icon={<SaveOutlined />} size="large">
                保存并生效
              </Button>
              {profileData && !isProfileEmpty(profileData) ? (
                <Button size="large" onClick={cancelEdit}>
                  取消
                </Button>
              ) : null}
            </Space>
          </Space>
        </Form>
      </div>

      <Modal
        title="选择完善画像的方式"
        open={improveOpen}
        onCancel={() => setImproveOpen(false)}
        footer={null}
        width={720}
      >
        <Typography.Paragraph type="secondary">
          可以组合使用多种方式。来自材料和公开信息的 AI 建议都需要你确认后才会生效。
        </Typography.Paragraph>
        <Row gutter={[12, 12]}>
          <Col xs={24} md={8}>
            <Card hoverable onClick={() => chooseImproveMethod('upload')} style={{ height: '100%' }}>
              <FileAddOutlined style={{ color: '#2F54EB', fontSize: 24 }} />
              <Typography.Title level={5}>上传企业材料</Typography.Title>
              <Typography.Text type="secondary">上传中标通知、成交公告等，AI 提取带原文证据的案例。</Typography.Text>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card hoverable onClick={() => chooseImproveMethod('public')} style={{ height: '100%' }}>
              <GlobalOutlined style={{ color: '#2F54EB', fontSize: 24 }} />
              <Typography.Title level={5}>从公开信息补充</Typography.Title>
              <Typography.Text type="secondary">按企业名称检索公开网页，逐字段核对 AI 建议。</Typography.Text>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card hoverable onClick={() => chooseImproveMethod('manual')} style={{ height: '100%' }}>
              <EditOutlined style={{ color: '#2F54EB', fontSize: 24 }} />
              <Typography.Title level={5}>手动填写</Typography.Title>
              <Typography.Text type="secondary">直接维护能力、行业、区域、资质与典型案例。</Typography.Text>
            </Card>
          </Col>
        </Row>
      </Modal>

      {/* AI 画像成果：逐字段「当前 vs 建议」，用户决定合并/替换/忽略后才应用到表单 */}
      <Modal
        title="AI 画像成果（逐字段确认）"
        open={suggestOpen}
        onOk={applySuggest}
        onCancel={() => setSuggestOpen(false)}
        okText="应用所选"
        cancelText="放弃"
        width={760}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          AI 未产出的字段不在下方列表中，会保持你已填写的内容不变；应用后仍需点「保存并生效」才会入库。
        </Typography.Paragraph>
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          {suggestRows.map((r, idx) => (
            <div key={r.key} style={{ borderBottom: '1px solid #f0f0f0', paddingBottom: 12 }}>
              <Space size={10} align="center" style={{ marginBottom: 6 }}>
                <Typography.Text strong>{r.label}</Typography.Text>
                <Select
                  size="small"
                  style={{ width: 130 }}
                  value={r.action}
                  onChange={(v) =>
                    setSuggestRows((rs) =>
                      rs.map((x, i) => (i === idx ? { ...x, action: v } : x))
                    )
                  }
                  options={[
                    ...(r.kind === 'tags' &&
                    (r.current as string[]).length &&
                    (r.suggested as string[]).length
                      ? [{ value: 'merge', label: '合并（保留现有）' }]
                      : []),
                    {
                      value: 'replace',
                      label: (r.kind === 'tags' ? (r.current as string[]).length : r.current)
                        ? '替换'
                        : '填入',
                    },
                    { value: 'ignore', label: '忽略' },
                  ]}
                />
              </Space>
              <div style={{ fontSize: 12, display: 'grid', gridTemplateColumns: '44px 1fr', rowGap: 4 }}>
                <Typography.Text type="secondary">当前</Typography.Text>
                <span>
                  {r.kind === 'tags' ? (
                    (r.current as string[]).length ? (
                      (r.current as string[]).map((t) => <Tag key={t}>{t}</Tag>)
                    ) : (
                      <Typography.Text type="secondary">（空）</Typography.Text>
                    )
                  ) : (
                    (r.current as string) || <Typography.Text type="secondary">（空）</Typography.Text>
                  )}
                </span>
                <Typography.Text type="secondary">建议</Typography.Text>
                <span>
                  {r.kind === 'tags'
                    ? (r.suggested as string[]).map((t) => (
                        <Tag key={t} color="blue">{t}</Tag>
                      ))
                    : (r.suggested as string)}
                </span>
              </div>
            </div>
          ))}
        </Space>
      </Modal>

      {/* 保存确认：列出关键变更，明确告知将触发重评估 */}
      <Modal
        title="确认画像变更"
        open={confirmOpen}
        onOk={confirmSave}
        onCancel={() => setConfirmOpen(false)}
        confirmLoading={saving}
        okText="确认生效"
        cancelText="再改改"
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          本次修改：
        </Typography.Paragraph>
        <ul style={{ paddingLeft: 20, marginTop: 0 }}>
          {diffs.map((d) => (
            <li key={d}>
              <Typography.Text>{d}</Typography.Text>
            </li>
          ))}
        </ul>
        <Alert
          type="info"
          showIcon
          message="保存后将按新画像重新评估近 7 天的商机（已标记跟进的项目不受影响），结果稍后出现在工作台。"
        />
      </Modal>
    </AppLayout>
  );
}
