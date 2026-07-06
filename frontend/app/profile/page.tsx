'use client';

import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Col, Divider, Form, Input, InputNumber, Row, Select, Spin } from 'antd';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import type { ProfileData } from '@/lib/types';

const TAG_FIELDS: { name: keyof ProfileData; label: string; placeholder: string }[] = [
  { name: 'products', label: '主要产品', placeholder: '输入后回车添加，如：视频会议终端' },
  { name: 'services', label: '主要服务', placeholder: '如：系统集成、运维服务' },
  { name: 'industries', label: '覆盖行业', placeholder: '如：政务、教育、医疗' },
  { name: 'regions', label: '业务区域', placeholder: '如：江苏省、南京市' },
  { name: 'certifications', label: '资质证书', placeholder: '如：ISO9001、CMMI3' },
  { name: 'brands', label: '代理品牌', placeholder: '如：华为、海康威视' },
];

export default function ProfilePage() {
  const { message } = App.useApp();
  const [form] = Form.useForm<ProfileData>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<ProfileData>('/api/profile')
      .then((data) => {
        form.setFieldsValue(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [form]);

  const onFinish = async (values: ProfileData) => {
    const payload: ProfileData = {
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
    };
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
    <AppLayout>
      <Card title="企业能力画像">
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
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
          </div>
        ) : (
          <Form<ProfileData> form={form} layout="vertical" onFinish={onFinish}>
            <Row gutter={24}>
              <Col xs={24} md={12}>
                <Form.Item name="name" label="企业名称" rules={[{ required: true, message: '请输入企业名称' }]}>
                  <Input placeholder="企业全称" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="description" label="企业简介">
              <Input.TextArea rows={3} placeholder="企业主营业务、核心能力简述" />
            </Form.Item>
            <Row gutter={24}>
              {TAG_FIELDS.map((f) => (
                <Col xs={24} md={12} key={f.name}>
                  <Form.Item name={f.name} label={f.label}>
                    <Select mode="tags" placeholder={f.placeholder} open={false} suffixIcon={null} tokenSeparators={[',', '，']} />
                  </Form.Item>
                </Col>
              ))}
            </Row>
            <Form.Item name="cases_text" label="典型案例（文本）">
              <Input.TextArea rows={4} placeholder="过往项目案例描述，用于 AI 匹配参考" />
            </Form.Item>
            <Divider orientation="left" plain>
              推荐过滤条件
            </Divider>
            <Row gutter={24}>
              <Col xs={24} md={12}>
                <Form.Item name={['filter', 'regions']} label="仅关注地区">
                  <Select mode="tags" placeholder="留空表示不限地区" open={false} suffixIcon={null} tokenSeparators={[',', '，']} />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name={['filter', 'min_budget']} label="最低预算（元）">
                  <InputNumber style={{ width: '100%' }} min={0} placeholder="留空表示不限预算" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" htmlType="submit" loading={saving}>
                保存画像
              </Button>
            </Form.Item>
          </Form>
        )}
      </Card>
    </AppLayout>
  );
}
