'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import {
  Alert,
  Card,
  Collapse,
  Descriptions,
  Empty,
  List,
  Progress,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { FileTextOutlined, LinkOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import { FIELD_LABELS } from '@/lib/labels';
import type { FieldValue, ProjectDetail } from '@/lib/types';

interface FieldRow {
  key: string;
  label: string;
  field: FieldValue | undefined;
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

  const fieldRows: FieldRow[] = FIELD_LABELS.map(([key, label]) => ({
    key,
    label,
    field: data?.project?.fields?.[key],
  }));

  const columns: ColumnsType<FieldRow> = [
    { title: '字段', dataIndex: 'label', key: 'label', width: 110 },
    {
      title: '内容',
      key: 'value',
      render: (_, row) => (
        <div>
          <div>{row.field?.value ?? '-'}</div>
          {row.field?.evidence ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              依据：{row.field.evidence}
            </Typography.Text>
          ) : null}
        </div>
      ),
    },
    {
      title: '置信度',
      key: 'confidence',
      width: 160,
      render: (_, row) => {
        if (!row.field || typeof row.field.confidence !== 'number') return '-';
        const c = row.field.confidence;
        return (
          <Progress
            percent={Math.round(c * 100)}
            size="small"
            strokeColor={c < 0.7 ? '#faad14' : '#52c41a'}
          />
        );
      },
    },
  ];

  return (
    <AppLayout>
      {loading ? (
        <div style={{ textAlign: 'center', padding: 64 }}>
          <Spin size="large" />
        </div>
      ) : error ? (
        <Alert type="error" showIcon message="项目详情加载失败" description={error} />
      ) : !data ? (
        <Empty description="未找到该项目" />
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card>
            <Typography.Title level={4} style={{ marginTop: 0 }}>
              {data.announcement.title}
            </Typography.Title>
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
              <Descriptions.Item label="地区">{data.announcement.region ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="采购单位">{data.announcement.buyer ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="发布时间">{data.announcement.publish_time ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="原文链接">
                {data.announcement.url ? (
                  <a href={data.announcement.url} target="_blank" rel="noreferrer">
                    <LinkOutlined /> 查看原文
                  </a>
                ) : (
                  '-'
                )}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card
            title="结构化信息"
            extra={
              data.project?.category ? (
                <Space size={4}>
                  {data.project.category.main ? <Tag color="blue">{data.project.category.main}</Tag> : null}
                  {data.project.category.sub ? <Tag>{data.project.category.sub}</Tag> : null}
                </Space>
              ) : null
            }
          >
            {data.project ? (
              <>
                {data.project.summary ? (
                  <Typography.Paragraph type="secondary">{data.project.summary}</Typography.Paragraph>
                ) : null}
                <Table<FieldRow>
                  rowKey="key"
                  columns={columns}
                  dataSource={fieldRows}
                  pagination={false}
                  size="small"
                />
              </>
            ) : (
              <Empty description="该公告尚未完成 AI 结构化解析" />
            )}
          </Card>

          <Collapse
            items={[
              {
                key: 'clean_text',
                label: '公告正文全文',
                children: data.announcement.clean_text ? (
                  <pre
                    style={{
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                      margin: 0,
                      fontFamily: 'inherit',
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

          <Card title="附件列表">
            {data.attachments?.length ? (
              <List
                size="small"
                dataSource={data.attachments}
                renderItem={(att) => (
                  <List.Item>
                    <Space>
                      <FileTextOutlined />
                      <Typography.Text>{att.filename}</Typography.Text>
                      <Tag>{att.status}</Tag>
                      {att.needs_ocr ? <Tag color="orange">需 OCR</Tag> : null}
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
