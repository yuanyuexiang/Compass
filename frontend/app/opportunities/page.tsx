'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Alert, Button, Card, Empty, Input, Skeleton, Space, Switch, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CloseOutlined, EnvironmentOutlined, RobotOutlined } from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import { formatDateTime, pipelineStatusLabel } from '@/lib/labels';
import type { AnnouncementItem, AnnouncementList, NlSearchResult } from '@/lib/types';

const PAGE_SIZE = 10;

// 进详情页返回后恢复查询条件/页码/AI 搜索结果（会话级，关标签页即清）
const STATE_KEY = 'compass-opportunities-state';

type SavedState = {
  keyword?: string;
  region?: string;
  page?: number;
  onlyMyRegion?: boolean;
  includeResults?: boolean;
  nlQuery?: string;
  nlResult?: NlSearchResult | null;
  nlFilters?: [string, unknown][];
};

function readSavedState(): SavedState {
  try {
    return JSON.parse(sessionStorage.getItem(STATE_KEY) ?? '{}') as SavedState;
  } catch {
    return {};
  }
}

export default function OpportunitiesPage() {
  const router = useRouter();
  const [keyword, setKeyword] = useState('');
  const [region, setRegion] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<AnnouncementItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [firstLoad, setFirstLoad] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [nlQuery, setNlQuery] = useState('');
  const [nlLoading, setNlLoading] = useState(false);
  const [nlResult, setNlResult] = useState<NlSearchResult | null>(null);
  const [nlFilters, setNlFilters] = useState<[string, unknown][]>([]);

  // 画像「仅关注地区」：默认按其过滤商机查询（与推荐口径统一），可切到全部地区
  const [profileRegions, setProfileRegions] = useState<string[]>([]);
  const [onlyMyRegion, setOnlyMyRegion] = useState(true);
  const regionScoped = profileRegions.length > 0 && !profileRegions.includes('全国');
  // 中标/成交等结果类公告默认隐藏（已无法投标）；打开可看竞争情报
  const [includeResults, setIncludeResults] = useState(false);

  const load = useCallback(
    async (p: number, kw: string, rg: string, onlyRegion: boolean, incResults: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String((p - 1) * PAGE_SIZE),
      });
      if (kw) params.set('keyword', kw);
      if (rg) params.set('region', rg);
      if (!onlyRegion) params.set('all_regions', 'true');
      if (incResults) params.set('include_results', 'true');
      const data = await apiFetch<AnnouncementList>(`/api/announcements?${params.toString()}`);
      setItems(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setItems([]);
      setTotal(0);
      setError((e as Error).message);
    } finally {
      setLoading(false);
      setFirstLoad(false);
    }
    },
    []
  );

  useEffect(() => {
    const saved = readSavedState();
    const p = saved.page && saved.page > 0 ? saved.page : 1;
    const kw = saved.keyword ?? '';
    const rg = saved.region ?? '';
    const only = saved.onlyMyRegion ?? true;
    const inc = saved.includeResults ?? false;
    setKeyword(kw);
    setRegion(rg);
    setPage(p);
    setOnlyMyRegion(only);
    setIncludeResults(inc);
    if (saved.nlResult) {
      setNlQuery(saved.nlQuery ?? '');
      setNlResult(saved.nlResult);
      setNlFilters(saved.nlFilters ?? []);
    }
    load(p, kw, rg, only, inc);
  }, [load]);

  // 状态变化即存 sessionStorage；跳过首次（恢复前的默认值），避免覆盖已存条件
  const skipFirstSave = useRef(true);
  useEffect(() => {
    if (skipFirstSave.current) {
      skipFirstSave.current = false;
      return;
    }
    const state: SavedState = {
      keyword, region, page, onlyMyRegion, includeResults, nlQuery, nlResult, nlFilters,
    };
    sessionStorage.setItem(STATE_KEY, JSON.stringify(state));
  }, [keyword, region, page, onlyMyRegion, includeResults, nlQuery, nlResult, nlFilters]);

  // 拉画像「仅关注地区」用于开关展示；过滤本身由后端按画像执行，此处不影响正确性
  useEffect(() => {
    apiFetch<{ filter?: { regions?: string[] } }>('/api/profile')
      .then((p) => setProfileRegions(p.filter?.regions ?? []))
      .catch(() => {
        // 画像拉取失败时隐藏开关，退化为后端默认行为
      });
  }, []);

  const doSearch = () => {
    setNlResult(null);
    setPage(1);
    load(1, keyword, region, onlyMyRegion, includeResults);
  };

  const doNlSearch = async (q: string, onlyRegion = onlyMyRegion, incResults = includeResults) => {
    if (!q.trim()) return;
    setNlLoading(true);
    setError(null);
    try {
      const data = await apiFetch<NlSearchResult>('/api/search/nl', {
        method: 'POST',
        body: JSON.stringify({
          query: q.trim(),
          all_regions: !onlyRegion,
          include_results: incResults,
        }),
      });
      setNlResult(data);
      setNlFilters(
        Object.entries(data.filters ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== '')
      );
    } catch (e) {
      setNlResult(null);
      setNlFilters([]);
      setError((e as Error).message);
    } finally {
      setNlLoading(false);
    }
  };

  const exitNl = () => {
    setNlResult(null);
    setNlFilters([]);
  };

  // 切换地区范围：同时作用于普通列表与 AI 搜索，保持两种模式口径一致
  const toggleRegion = (v: boolean) => {
    setOnlyMyRegion(v);
    if (nlResult) {
      doNlSearch(nlQuery, v);
    } else {
      setPage(1);
      load(1, keyword, region, v, includeResults);
    }
  };

  // 切换是否显示中标/成交等结果类公告（同样作用于两种搜索模式）
  const toggleResults = (v: boolean) => {
    setIncludeResults(v);
    if (nlResult) {
      doNlSearch(nlQuery, onlyMyRegion, v);
    } else {
      setPage(1);
      load(1, keyword, region, onlyMyRegion, v);
    }
  };

  const columns: ColumnsType<AnnouncementItem> = [
    {
      title: '公告标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (title: string) => (
        <Typography.Text strong style={{ color: '#2F54EB' }}>
          {title}
        </Typography.Text>
      ),
    },
    {
      title: '类型',
      dataIndex: 'ann_type',
      key: 'ann_type',
      width: 150,
      render: (t: string | null) => (t ? <Tag>{t}</Tag> : '-'),
    },
    { title: '地区', dataIndex: 'region', key: 'region', width: 110, render: (v: string | null) => v ?? '-' },
    {
      title: '采购单位',
      dataIndex: 'buyer',
      key: 'buyer',
      width: 200,
      ellipsis: true,
      render: (v: string | null) => v ?? '-',
    },
    {
      title: '发布时间',
      dataIndex: 'publish_time',
      key: 'publish_time',
      width: 150,
      render: (v: string | null) => formatDateTime(v),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (s: string | null) => (s ? <Tag color="geekblue">{pipelineStatusLabel(s)}</Tag> : '-'),
    },
  ];

  return (
    <AppLayout title="商机查询" subtitle="关键词精确筛选，或让 AI 理解你的一句话需求">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* AI 自然语言搜索：品牌渐变描边容器 */}
        <div className="nl-search-wrap">
          <div className="nl-search-inner">
            <Space size={10} style={{ width: '100%' }} direction="vertical">
              <Space size={8}>
                <span className="ai-badge">
                  <RobotOutlined /> AI
                </span>
                <Typography.Text strong>自然语言搜索</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  用一句话描述你要找的项目
                </Typography.Text>
              </Space>
              <Input.Search
                size="large"
                placeholder="例如：查找江苏省预算超过300万的 AI 项目"
                enterButton="AI 搜索"
                loading={nlLoading}
                value={nlQuery}
                onChange={(e) => setNlQuery(e.target.value)}
                onSearch={(v) => doNlSearch(v)}
                allowClear
              />
              {nlResult?.degraded === 'quota' ? (
                <Typography.Text type="warning" style={{ fontSize: 13 }}>
                  今日 AI 搜索次数已用完，已按关键词搜索
                </Typography.Text>
              ) : null}
              {nlResult ? (
                <Space size={[6, 6]} wrap>
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    AI 解析条件：
                  </Typography.Text>
                  {nlFilters.length === 0 ? (
                    <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                      （无）
                    </Typography.Text>
                  ) : (
                    nlFilters.map(([k, v]) => (
                      <Tag
                        color="blue"
                        key={k}
                        closable
                        onClose={() => setNlFilters((fs) => fs.filter(([fk]) => fk !== k))}
                      >
                        {k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                      </Tag>
                    ))
                  )}
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    共 {nlResult.total} 条结果
                  </Typography.Text>
                  <Button size="small" icon={<CloseOutlined />} onClick={exitNl}>
                    退出 AI 搜索
                  </Button>
                </Space>
              ) : null}
            </Space>
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            flexWrap: 'wrap',
            padding: '0 4px',
          }}
        >
          {regionScoped ? (
            <>
              <Switch size="small" checked={onlyMyRegion} onChange={toggleRegion} />
              <Typography.Text style={{ fontSize: 13 }}>仅看关注地区</Typography.Text>
              <Space size={4} wrap>
                {profileRegions.map((r) => (
                  <Tag key={r} color={onlyMyRegion ? 'blue' : 'default'} icon={<EnvironmentOutlined />}>
                    {r}
                  </Tag>
                ))}
              </Space>
              <span style={{ width: 12 }} />
            </>
          ) : null}
          <Switch size="small" checked={includeResults} onChange={toggleResults} />
          <Typography.Text style={{ fontSize: 13 }}>包含结果公告</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {includeResults
              ? '正在显示中标/成交/废标等已结束公告（竞争情报参考）'
              : '已隐藏中标/成交/废标等已结束公告，只看还能投的'}
          </Typography.Text>
        </div>

        <Card
          className="compass-card"
          title={nlResult ? 'AI 搜索结果' : '公告列表'}
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
          {firstLoad && loading ? (
            <Skeleton active paragraph={{ rows: 6 }} />
          ) : (
            <Table<AnnouncementItem>
              size="middle"
              rowKey={(r) => String(r.id)}
              columns={columns}
              loading={loading || nlLoading}
              dataSource={nlResult ? nlResult.items : items}
              locale={{
                emptyText: (
                  <Empty description="暂无公告数据，采集任务运行后将自动入库" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ),
              }}
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
                        load(p, keyword, region, onlyMyRegion, includeResults);
                      },
                    }
              }
            />
          )}
        </Card>
      </Space>
    </AppLayout>
  );
}
