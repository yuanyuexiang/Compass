'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Progress,
  Row,
  Skeleton,
  Space,
  Tag,
  Typography,
} from 'antd';
import { ArrowRightOutlined, LinkOutlined, WarningOutlined } from '@ant-design/icons';
import { apiFetch } from '@/lib/api';
import { FIELD_LABELS, formatDateTime } from '@/lib/labels';
import type { FieldValue, ProjectDetail } from '@/lib/types';

function FieldBlock({ label, field }: { label: string; field: FieldValue | undefined }) {
  const confidence = typeof field?.confidence === 'number' ? field.confidence : null;
  const low = confidence !== null && confidence < 0.7;
  return (
    <div className="opportunity-field">
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{label}</Typography.Text>
      <div className="opportunity-field-value">{field?.value ?? '-'}</div>
      {confidence !== null ? (
        <Progress
          percent={Math.round(confidence * 100)}
          showInfo={false}
          size="small"
          strokeColor={low ? '#FAAD14' : '#2F54EB'}
          style={{ margin: '4px 0 0' }}
        />
      ) : null}
      {field?.evidence ? <div className="evidence-quote">依据：{field.evidence}</div> : null}
    </div>
  );
}

export default function OpportunityDetailPanel({ id }: { id: number | string | null }) {
  const [data, setData] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id == null) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiFetch<ProjectDetail>(`/api/projects/${id}`)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setData(null);
          setError(e.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (id == null) {
    return <Card className="compass-card opportunity-detail"><Empty description="从左侧选择一个商机查看详情" /></Card>;
  }
  if (loading) {
    return <Card className="compass-card opportunity-detail"><Skeleton active paragraph={{ rows: 12 }} /></Card>;
  }
  if (error) {
    return <Alert type="error" showIcon message="项目详情加载失败" description={error} />;
  }
  if (!data) {
    return <Card className="compass-card opportunity-detail"><Empty description="未找到该项目" /></Card>;
  }

  return (
    <Card
      className="compass-card opportunity-detail"
      title={<Typography.Text strong>{data.announcement.title}</Typography.Text>}
      extra={<Link href={`/projects/${id}`}><Button type="link" size="small">完整详情 <ArrowRightOutlined /></Button></Link>}
    >
      <Space direction="vertical" size={18} style={{ width: '100%' }}>
        <Descriptions size="small" column={2}>
          <Descriptions.Item label="地区">{data.announcement.region ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="发布时间">{formatDateTime(data.announcement.publish_time)}</Descriptions.Item>
          <Descriptions.Item label="采购单位" span={2}>{data.announcement.buyer ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="公告原文" span={2}>
            <a href={data.announcement.url} target="_blank" rel="noreferrer" style={{ color: '#2F54EB' }}>
              <LinkOutlined /> 打开原始公告
            </a>
          </Descriptions.Item>
        </Descriptions>

        <div>
          <Space size={6} wrap style={{ marginBottom: 8 }}>
            <Typography.Text strong>AI 结构化信息</Typography.Text>
            {data.project?.category?.main ? <Tag color="geekblue">{data.project.category.main}</Tag> : null}
            {data.project?.category?.sub ? <Tag>{data.project.category.sub}</Tag> : null}
          </Space>
          {data.project ? (
            <>
              {data.project.summary ? (
                <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
                  {data.project.summary}
                </Typography.Paragraph>
              ) : null}
              <Row gutter={[10, 10]}>
                {FIELD_LABELS.map(([key, label]) => (
                  <Col xs={24} xl={12} key={key}>
                    <FieldBlock label={label} field={data.project?.fields?.[key]} />
                  </Col>
                ))}
              </Row>
            </>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未完成 AI 结构化解析" />}
        </div>

        <Collapse
          size="small"
          items={[{
            key: 'text',
            label: '公告正文',
            children: data.announcement.clean_text ? (
              <pre className="opportunity-clean-text">{data.announcement.clean_text}</pre>
            ) : '暂无正文内容',
          }]}
        />
        {data.attachments?.some((item) => item.needs_ocr) ? (
          <Typography.Text type="warning"><WarningOutlined /> 部分附件需要 OCR 后才能读取</Typography.Text>
        ) : null}
      </Space>
    </Card>
  );
}
