'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Alert, Button, Card, Input, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CloseOutlined, RobotOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import type { AnnouncementItem, AnnouncementList, NlSearchResult } from '@/lib/types';

const PAGE_SIZE = 10;

export default function OpportunitiesPage() {
  const router = useRouter();
  const [keyword, setKeyword] = useState('');
  const [region, setRegion] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<AnnouncementItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [nlQuery, setNlQuery] = useState('');
  const [nlLoading, setNlLoading] = useState(false);
  const [nlResult, setNlResult] = useState<NlSearchResult | null>(null);

  const load = useCallback(
    async (p: number, kw: string, rg: string) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String((p - 1) * PAGE_SIZE),
        });
        if (kw) params.set('keyword', kw);
        if (rg) params.set('region', rg);
        const data = await apiFetch<AnnouncementList>(`/api/announcements?${params.toString()}`);
        setItems(data.items ?? []);
        setTotal(data.total ?? 0);
      } catch (e) {
        setItems([]);
        setTotal(0);
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    load(1, '', '');
  }, [load]);

  const doSearch = () => {
    setNlResult(null);
    setPage(1);
    load(1, keyword, region);
  };

  const doNlSearch = async (q: string) => {
    if (!q.trim()) return;
    setNlLoading(true);
    setError(null);
    try {
      const data = await apiFetch<NlSearchResult>('/api/search/nl', {
        method: 'POST',
        body: JSON.stringify({ query: q.trim() }),
      });
      setNlResult(data);
    } catch (e) {
      setNlResult(null);
      setError((e as Error).message);
    } finally {
      setNlLoading(false);
    }
  };

  const columns: ColumnsType<AnnouncementItem> = [
    {
      title: '公告标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (title: string) => <Typography.Text style={{ color: '#1677ff' }}>{title}</Typography.Text>,
    },
    {
      title: '类型',
      dataIndex: 'ann_type',
      key: 'ann_type',
      width: 110,
      render: (t: string | null) => (t ? <Tag>{t}</Tag> : '-'),
    },
    { title: '地区', dataIndex: 'region', key: 'region', width: 110, render: (v: string | null) => v ?? '-' },
    { title: '采购单位', dataIndex: 'buyer', key: 'buyer', width: 200, ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '发布时间', dataIndex: 'publish_time', key: 'publish_time', width: 160, render: (v: string | null) => v ?? '-' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: string | null) => (s ? <Tag color="blue">{s}</Tag> : '-'),
    },
  ];

  const nlFilterEntries = nlResult
    ? Object.entries(nlResult.filters ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== '')
    : [];

  return (
    <AppLayout>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card size="small">
          <Input.Search
            prefix={<RobotOutlined />}
            placeholder="AI 自然语言搜索，例如：查找江苏省预算超过300万的 AI 项目"
            enterButton="AI 搜索"
            loading={nlLoading}
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            onSearch={doNlSearch}
            allowClear
          />
          {nlResult ? (
            <div style={{ marginTop: 12 }}>
              <Space size={[4, 4]} wrap>
                <Typography.Text type="secondary">AI 解析条件：</Typography.Text>
                {nlFilterEntries.length === 0 ? (
                  <Typography.Text type="secondary">（无）</Typography.Text>
                ) : (
                  nlFilterEntries.map(([k, v]) => (
                    <Tag color="blue" key={k}>
                      {k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                    </Tag>
                  ))
                )}
                <Typography.Text type="secondary">共 {nlResult.total} 条结果</Typography.Text>
                <Button size="small" icon={<CloseOutlined />} onClick={() => setNlResult(null)}>
                  退出 AI 搜索
                </Button>
              </Space>
            </div>
          ) : null}
        </Card>

        <Card
          title={nlResult ? 'AI 搜索结果' : '商机查询'}
          extra={
            nlResult ? null : (
              <Space>
                <Input
                  placeholder="关键词"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onPressEnter={doSearch}
                  style={{ width: 200 }}
                  allowClear
                />
                <Input
                  placeholder="地区"
                  value={region}
                  onChange={(e) => setRegion(e.target.value)}
                  onPressEnter={doSearch}
                  style={{ width: 140 }}
                  allowClear
                />
                <Button type="primary" onClick={doSearch}>
                  查询
                </Button>
              </Space>
            )
          }
        >
          {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
          <Table<AnnouncementItem>
            rowKey={(r) => String(r.id)}
            columns={columns}
            loading={loading || nlLoading}
            dataSource={nlResult ? nlResult.items : items}
            locale={{ emptyText: '暂无公告数据' }}
            onRow={(record) => ({
              onClick: () => router.push(`/projects/${record.id}`),
              style: { cursor: 'pointer' },
            })}
            pagination={
              nlResult
                ? { pageSize: PAGE_SIZE, showSizeChanger: false }
                : {
                    current: page,
                    pageSize: PAGE_SIZE,
                    total,
                    showSizeChanger: false,
                    showTotal: (t) => `共 ${t} 条`,
                    onChange: (p) => {
                      setPage(p);
                      load(p, keyword, region);
                    },
                  }
            }
          />
        </Card>
      </Space>
    </AppLayout>
  );
}
