'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  Upload,
} from 'antd';
import {
  CheckOutlined,
  DeleteOutlined,
  FileSearchOutlined,
  InboxOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { apiFetch } from '@/lib/api';
import { formatDateTime } from '@/lib/labels';
import type {
  ProfileFactItem,
  ProfileMaterialItem,
  ProjectCaseFactValue,
} from '@/lib/types';

const STATUS_META: Record<string, { label: string; color: string }> = {
  parsed: { label: '等待 AI 抽取', color: 'processing' },
  extracting: { label: 'AI 抽取中', color: 'processing' },
  extracted: { label: '已提取', color: 'success' },
  no_facts: { label: '未发现案例', color: 'default' },
  extract_failed: { label: '抽取失败', color: 'error' },
  needs_ocr: { label: '需要 OCR', color: 'warning' },
};

const ROLE_LABELS: Record<string, string> = {
  winner: '中标人',
  supplier: '成交供应商',
  consortium_member: '联合体成员',
  candidate: '中标候选人',
  mentioned: '仅被提及',
  unknown: '角色待确认',
};

const DOCUMENT_TYPES = [
  { value: 'auto', label: '自动识别（推荐）' },
  { value: 'award_notice', label: '中标/成交材料' },
  { value: 'contract', label: '合同材料' },
  { value: 'acceptance_report', label: '验收材料' },
  { value: 'company_presentation', label: '公司介绍/演示 PPT' },
  { value: 'solution', label: '解决方案' },
  { value: 'case_study', label: '案例集' },
  { value: 'product_manual', label: '产品手册' },
  { value: 'whitepaper', label: '技术白皮书' },
  { value: 'qualification', label: '资质与认证' },
  { value: 'other', label: '其他企业资料' },
];

const FACT_LABELS: Record<string, string> = {
  project_case: '项目案例',
  product_capability: '产品能力',
  service_capability: '服务能力',
  industry_capability: '行业能力',
  certification: '资质认证',
  brand_partnership: '合作品牌',
  company_description: '企业简介',
};

const SOURCE_LABELS: Record<string, string> = {
  self_declared: '企业自述',
  case_supported: '案例佐证',
  contract_proof: '合同/中标佐证',
  acceptance_proof: '验收佐证',
  certificate_proof: '证书佐证',
  tenant_confirmed: '人工确认',
};

export default function ProfileEvidencePanel({
  onProfileChanged,
  section = 'all',
  onCountsChange,
}: {
  onProfileChanged: () => void | Promise<void>;
  section?: 'all' | 'review' | 'materials';
  onCountsChange?: (counts: { pending: number; materials: number }) => void;
}) {
  const { message } = App.useApp();
  const [materials, setMaterials] = useState<ProfileMaterialItem[]>([]);
  const [facts, setFacts] = useState<ProfileFactItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [documentType, setDocumentType] = useState('auto');
  const [editing, setEditing] = useState<ProfileFactItem | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [caseForm] = Form.useForm<ProjectCaseFactValue>();

  const load = useCallback(async () => {
    try {
      const [materialRows, factRows] = await Promise.all([
        apiFetch<ProfileMaterialItem[]>('/api/profile/materials'),
        apiFetch<ProfileFactItem[]>('/api/profile/facts?status=pending'),
      ]);
      setMaterials(materialRows);
      setFacts(factRows);
      onCountsChange?.({ pending: factRows.length, materials: materialRows.length });
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  }, [message, onCountsChange]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!materials.some((item) => ['parsed', 'extracting'].includes(item.parse_status))) return;
    const timer = window.setTimeout(() => void load(), 3000);
    return () => window.clearTimeout(timer);
  }, [materials, load]);

  const upload = async (file: Blob, filename: string) => {
    setUploading(true);
    try {
      const body = new FormData();
      body.append('file', file, filename);
      body.append('document_type', documentType);
      await apiFetch('/api/profile/materials', { method: 'POST', body });
      message.success('资料已上传，AI 将在后台提取候选能力事实');
      await load();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const retry = async (id: number) => {
    try {
      await apiFetch(`/api/profile/materials/${id}/extract`, { method: 'POST' });
      message.success('已重新提交抽取');
      await load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const removeMaterial = async (id: number) => {
    try {
      await apiFetch(`/api/profile/materials/${id}`, { method: 'DELETE' });
      message.success('材料已删除');
      await load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const openConfirm = (fact: ProfileFactItem) => {
    setEditing(fact);
    caseForm.setFieldsValue(fact.value);
  };

  const confirmFact = async () => {
    if (!editing) return;
    const value = await caseForm.validateFields();
    setConfirming(true);
    try {
      await apiFetch(`/api/profile/facts/${editing.id}/confirm`, {
        method: 'POST',
        body: JSON.stringify({ value }),
      });
      message.success('事实已确认并写入正式画像');
      setEditing(null);
      await Promise.all([load(), onProfileChanged()]);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setConfirming(false);
    }
  };

  const rejectFact = async (id: number) => {
    try {
      await apiFetch(`/api/profile/facts/${id}/reject`, { method: 'POST' });
      message.success('已忽略该候选事实');
      await load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', marginBottom: 16 }}>
      {section !== 'review' ? <Card
        className="compass-card"
        title={<span><InboxOutlined style={{ marginRight: 6 }} />企业资料库</span>}
      >
        <Alert
          type="info"
          showIcon
          message="支持企业演示、解决方案、案例、履约与资质材料（PDF、PPTX、DOCX、TXT，最大 20MB）"
          description="请先移除身份证号、银行账户、签名等不需要进入画像的敏感信息。AI 结果必须经你确认才会影响正式画像。"
          style={{ marginBottom: 14 }}
        />
        <Space direction="vertical" style={{ width: '100%', marginBottom: 12 }}>
          <Typography.Text strong>资料类型</Typography.Text>
          <Select value={documentType} options={DOCUMENT_TYPES} onChange={setDocumentType} style={{ width: 260 }} />
        </Space>
        <Upload.Dragger
          accept=".pdf,.pptx,.docx,.txt"
          multiple={false}
          showUploadList={false}
          disabled={uploading}
          customRequest={({ file, onSuccess, onError }) => {
            if (!(file instanceof Blob)) {
              onError?.(new Error('无法读取文件'));
              return;
            }
            void upload(file, 'name' in file ? String(file.name) : 'material.pdf')
              .then(() => onSuccess?.({}))
              .catch((error) => onError?.(error as Error));
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖入企业资料</p>
          <p className="ant-upload-hint">原件按租户隔离保存，AI 仅生成带页码和原文证据的候选事实</p>
        </Upload.Dragger>

        <List
          style={{ marginTop: 14 }}
          loading={loading}
          locale={{ emptyText: '尚未上传画像材料' }}
          dataSource={materials}
          renderItem={(item) => {
            const status = STATUS_META[item.parse_status] ?? {
              label: item.parse_status,
              color: 'default',
            };
            return (
              <List.Item
                actions={[
                  ...(item.parse_status === 'extract_failed' || item.parse_status === 'no_facts'
                    ? [
                        <Button
                          key="retry"
                          type="link"
                          icon={<ReloadOutlined />}
                          onClick={() => void retry(item.id)}
                        >
                          重试
                        </Button>,
                      ]
                    : []),
                  <Popconfirm
                    key="delete"
                    title="删除这份材料？"
                    description="未确认的候选事实会一并删除。"
                    onConfirm={() => void removeMaterial(item.id)}
                  >
                    <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<FileSearchOutlined style={{ fontSize: 20, color: '#2F54EB' }} />}
                  title={<Space wrap><span>{item.filename}</span><Tag color={status.color}>{status.label}</Tag></Space>}
                  description={
                    <Space direction="vertical" size={2}>
                      <span>{DOCUMENT_TYPES.find((type) => type.value === item.document_type)?.label || item.document_type} · {formatDateTime(item.created_at)} · 已发现 {item.fact_count} 条事实</span>
                      {item.error ? <Typography.Text type="danger">{item.error}</Typography.Text> : null}
                    </Space>
                  }
                />
              </List.Item>
            );
          }}
        />
      </Card> : null}

      {section !== 'materials' ? <Card
        className="compass-card"
        title={<span><FileSearchOutlined style={{ marginRight: 6 }} />待确认建议</span>}
        extra={<Tag color={facts.length ? 'processing' : 'default'}>{facts.length} 条</Tag>}
      >
        {facts.length ? (
          <List
            dataSource={facts}
            renderItem={(fact) => (
              <List.Item
                actions={[
                  <Button key="confirm" type="primary" icon={<CheckOutlined />} onClick={() => openConfirm(fact)}>
                    核对并确认
                  </Button>,
                  <Popconfirm key="reject" title="忽略这条候选事实？" onConfirm={() => void rejectFact(fact.id)}>
                    <Button danger>忽略</Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space wrap>
                        <Typography.Text strong>{fact.value.project_name || fact.value.name || fact.value.description}</Typography.Text>
                      <Tag color="blue">{FACT_LABELS[fact.fact_type] || fact.fact_type}</Tag>
                      {fact.value.company_role ? <Tag>{ROLE_LABELS[fact.value.company_role]}</Tag> : null}
                      {fact.value.status === 'planned' ? <Tag color="warning">规划能力</Tag> : null}
                      <Tag>{SOURCE_LABELS[fact.source_strength] || fact.source_strength}</Tag>
                      <Tag color={fact.confidence >= 0.8 ? 'green' : 'orange'}>
                        可信度 {Math.round(fact.confidence * 100)}%
                      </Tag>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={5} style={{ width: '100%' }}>
                      <span>
                        {[fact.value.customer, fact.value.region, fact.value.amount_yuan != null
                          ? `${fact.value.amount_yuan / 10000} 万元`
                          : null].filter(Boolean).join(' · ') || '项目字段待补充'}
                      </span>
                      {fact.value.description && fact.fact_type !== 'company_description' ? <span>{fact.value.description}</span> : null}
                      {fact.value.services?.length ? (
                        <Space size={[4, 4]} wrap>{fact.value.services.map((item) => <Tag key={item}>{item}</Tag>)}</Space>
                      ) : null}
                      {fact.evidence ? (
                        <Typography.Text type="secondary">
                          证据：{fact.evidence.filename}{fact.evidence.page ? ` 第${fact.evidence.page}页` : ''}——“{fact.evidence.quote}”
                        </Typography.Text>
                      ) : null}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无待确认的 AI 候选事实" />
        )}
      </Card> : null}

      <Modal
        title="核对 AI 识别结果"
        open={!!editing}
        onOk={() => void confirmFact()}
        onCancel={() => setEditing(null)}
        confirmLoading={confirming}
        okText="确认并写入当前画像"
        width={920}
      >
        <Row gutter={[24, 16]}>
          <Col xs={24} md={9}>
            <Typography.Text strong>材料原文</Typography.Text>
            {editing?.evidence ? (
              <div style={{ marginTop: 10, padding: 16, background: '#f7f8fa', borderRadius: 8, minHeight: 230 }}>
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  <Space wrap>
                    <FileSearchOutlined style={{ color: '#2F54EB' }} />
                    <Typography.Text>{editing.evidence.filename}</Typography.Text>
                    {editing.evidence.page ? <Tag>第 {editing.evidence.page} 页</Tag> : null}
                  </Space>
                  <Typography.Paragraph style={{ margin: 0, lineHeight: 1.8 }}>
                    “{editing.evidence.quote}”
                  </Typography.Paragraph>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    右侧内容由 AI 从这段原文提取，请核对事实内容、当前/规划状态及证据是否一致。
                  </Typography.Text>
                </Space>
              </div>
            ) : <Alert type="warning" message="这条建议没有可展示的原文证据" />}
          </Col>
          <Col xs={24} md={15}>
            <Typography.Text strong>将写入画像的内容</Typography.Text>
            <Form form={caseForm} layout="vertical" style={{ marginTop: 10 }}>
              {editing?.fact_type !== 'project_case' ? (
                <>
                  {editing?.fact_type === 'company_description' ? (
                    <Form.Item name="description" label="企业简介" rules={[{ required: true, message: '请填写企业简介' }]}>
                      <Input.TextArea rows={6} />
                    </Form.Item>
                  ) : (
                    <>
                      <Form.Item name="name" label="事实名称" rules={[{ required: true, message: '请填写名称' }]}><Input /></Form.Item>
                      <Form.Item name="description" label="能力说明"><Input.TextArea rows={3} /></Form.Item>
                      {['product_capability', 'service_capability', 'industry_capability'].includes(editing?.fact_type || '') ? (
                        <Form.Item name="status" label="能力状态" rules={[{ required: true }]}>
                          <Select options={[{ value: 'current', label: '当前能力' }, { value: 'planned', label: '规划能力（不参与匹配）' }]} />
                        </Form.Item>
                      ) : null}
                      {editing?.fact_type === 'certification' ? <>
                        <Form.Item name="issuer" label="颁发机构"><Input /></Form.Item>
                        <Form.Item name="valid_until" label="有效期至"><Input /></Form.Item>
                      </> : null}
                      {editing?.fact_type === 'brand_partnership' ? <Form.Item name="relationship" label="合作关系"><Input /></Form.Item> : null}
                    </>
                  )}
                </>
              ) : <>
              <Form.Item name="project_name" label="项目名称" rules={[{ required: true, message: '请填写项目名称' }]}>
                <Input />
              </Form.Item>
              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Form.Item name="company_role" label="企业角色" rules={[{ required: true }]}>
                    <Select options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="amount_yuan" label="项目金额（元）">
                    <InputNumber min={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col xs={24} md={12}><Form.Item name="customer" label="采购人/建设单位"><Input /></Form.Item></Col>
                <Col xs={24} md={12}><Form.Item name="region" label="项目地区"><Input /></Form.Item></Col>
              </Row>
              <Form.Item name="awarded_at" label="中标时间"><Input placeholder="YYYY-MM-DD 或 YYYY-MM" /></Form.Item>
              <Form.Item name="services" label="明确交付范围">
                <Select mode="tags" tokenSeparators={[',', '，', '、', ';', '；']} />
              </Form.Item>
              </>}
            </Form>
          </Col>
        </Row>
      </Modal>
    </Space>
  );
}
