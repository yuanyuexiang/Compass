'use client';

import { useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from 'antd';
import { RobotOutlined, SaveOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import type { ProfileData, ProfileSuggestResult } from '@/lib/types';

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

  // AI 生成画像：输入企业名 → 联网整理草稿 → 预填表单，用户核对后再保存
  const [aiName, setAiName] = useState('');
  const [suggesting, setSuggesting] = useState(false);
  const [suggestMeta, setSuggestMeta] = useState<Omit<ProfileSuggestResult, 'draft'> | null>(null);

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
      form.setFieldsValue(normalizeProfile(draft));
      setSuggestMeta({ sources: r.sources, confidence: r.confidence, note: r.note });
      message.success('已生成画像草稿，请核对补充后保存');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSuggesting(false);
    }
  };

  useEffect(() => {
    apiFetch<ProfileData>('/api/profile')
      .then((data) => {
        form.setFieldsValue(normalizeProfile(data));
        // AI 生成画像默认按注册企业名联网检索（可改，比如想按品牌名搜）
        setAiName((prev) => prev || data.name || '');
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [form]);

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
    setSaving(true);
    try {
      await apiFetch<{ ok: boolean }>('/api/profile', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      message.success('企业画像已保存');
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
      {/* Form 始终挂载（加载时隐藏），避免 useForm 实例未连接的警告 */}
      <div style={{ display: loading ? 'none' : undefined }}>
        <Form<ProfileData> form={form} layout="vertical" onFinish={onFinish}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card className="compass-card" title={<span><RobotOutlined style={{ color: '#2F54EB', marginRight: 6 }} />AI 生成画像</span>}>
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
                    suggestMeta.sources.length ? (
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

            <Button type="primary" htmlType="submit" loading={saving} icon={<SaveOutlined />} size="large">
              保存画像
            </Button>
          </Space>
        </Form>
      </div>
    </AppLayout>
  );
}
