'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import {
  Alert,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  List,
  Progress,
  Row,
  Skeleton,
  Space,
  Tag,
  Typography,
} from 'antd';
import { FileTextOutlined, LinkOutlined, WarningOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import { FIELD_LABELS } from '@/lib/labels';
import type { FieldValue, ProjectDetail } from '@/lib/types';

function FieldBlock({ label, field }: { label: string; field: FieldValue | undefined }) {
  const conf = typeof field?.confidence === 'number' ? field.confidence : null;
  const low = conf !== null && conf < 0.7;
  return (
    <div style={{ padding: '12px 14px', background: '#FAFBFD', borderRadius: 10, height: '100%' }}>
      <div style={{ fontSize: 13, color: 'rgba(0, 0, 0, 0.45)', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 14, color: 'rgba(0, 0, 0, 0.88)', wordBreak: 'break-all' }}>{field?.value ?? '-'}</div>
      {conf !== null ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
          <Progress
            percent={Math.round(conf * 100)}
            size="small"
            strokeColor={low ? '#FAAD14' : '#2F54EB'}
            style={{ maxWidth: 140, marginBottom: 0 }}
          />
          {low ? (
            <span style={{ fontSize: 12, color: '#D48806', whiteSpace: 'nowrap' }}>
              <WarningOutlined style={{ marginRight: 3 }} />
              低置信
            </span>
          ) : null}
        </div>
      ) : null}
      {field?.evidence ? <div className="evidence-quote">依据：{field.evidence}</div> : null}
    </div>
  );
}

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [data, setData] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    apiFetch<ProjectDetail>(`/api/projects/${id}`)
      .then(setData)
      .catch((e: Error) => {
        setData(null);
        setError(e.message);
      })
      .finally(() => setLoading(false));
  }, [id]);

  return (
    <AppLayout title="项目详情" subtitle="公告原文与 AI 结构化解析结果">
      {loading ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card className="compass-card">
            <Skeleton active paragraph={{ rows: 2 }} />
          </Card>
          <Card className="compass-card">
            <Skeleton active paragraph={{ rows: 8 }} />
          </Card>
        </Space>
      ) : error ? (
        <Alert type="error" showIcon message="项目详情加载失败" description={error} />
      ) : !data ? (
        <Card className="compass-card">
          <Empty description="未找到该项目" />
        </Card>
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card className="compass-card">
            <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 12 }}>
              {data.announcement.title}
            </Typography.Title>
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
              <Descriptions.Item label="地区">{data.announcement.region ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="采购单位">{data.announcement.buyer ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="发布时间">{data.announcement.publish_time ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="原文链接">
                {data.announcement.url ? (
                  <a href={data.announcement.url} target="_blank" rel="noreferrer" style={{ color: '#2F54EB' }}>
                    <LinkOutlined /> 查看原文
                  </a>
                ) : (
                  '-'
                )}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card
            className="compass-card"
            title="AI 结构化信息"
            extra={
              data.project?.category ? (
                <Space size={4}>
                  {data.project.category.main ? <Tag color="geekblue">{data.project.category.main}</Tag> : null}
                  {data.project.category.sub ? <Tag>{data.project.category.sub}</Tag> : null}
                </Space>
              ) : null
            }
          >
            {data.project ? (
              <>
                {data.project.summary ? (
                  <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
                    {data.project.summary}
                  </Typography.Paragraph>
                ) : null}
                <Row gutter={[12, 12]}>
                  {FIELD_LABELS.map(([key, label]) => (
                    <Col xs={24} md={12} key={key}>
                      <FieldBlock label={label} field={data.project?.fields?.[key]} />
                    </Col>
                  ))}
                </Row>
              </>
            ) : (
              <Empty description="该公告尚未完成 AI 结构化解析，解析完成后自动展示" />
            )}
          </Card>

          <Collapse
            className="compass-card"
            style={{ background: '#fff' }}
            items={[
              {
                key: 'clean_text',
                label: <Typography.Text strong>公告正文全文</Typography.Text>,
                children: data.announcement.clean_text ? (
                  <pre
                    style={{
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                      margin: 0,
                      fontFamily: 'inherit',
                      fontSize: 13,
                      color: 'rgba(0, 0, 0, 0.65)',
                      maxHeight: 480,
                      overflow: 'auto',
                    }}
                  >
                    {data.announcement.clean_text}
                  </pre>
                ) : (
                  <Typography.Text type="secondary">暂无正文内容</Typography.Text>
                ),
              },
            ]}
          />

          <Card className="compass-card" title="附件列表">
            {data.attachments?.length ? (
              <List
                size="small"
                dataSource={data.attachments}
                renderItem={(att) => (
                  <List.Item>
                    <Space>
                      <FileTextOutlined style={{ color: '#2F54EB' }} />
                      <Typography.Text>{att.filename}</Typography.Text>
                      <Tag>{att.status}</Tag>
                      {att.needs_ocr ? (
                        <Tag color="warning" icon={<WarningOutlined />}>
                          需 OCR
                        </Tag>
                      ) : null}
                    </Space>
                  </List.Item>
                )}
              />
            ) : (
              <Typography.Text type="secondary">无附件</Typography.Text>
            )}
          </Card>
        </Space>
      )}
    </AppLayout>
  );
}
