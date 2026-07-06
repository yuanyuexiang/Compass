'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Alert,
  App,
  Card,
  Col,
  Empty,
  Rate,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import {
  ADVICE_COLORS,
  FOLLOW_STATUSES,
  RISK_KEYS,
  RISK_LABELS,
  formatBudget,
  pipelineStatusLabel,
} from '@/lib/labels';
import type { FollowStatus, Recommendation, Stats } from '@/lib/types';

const MIN_STAR_OPTIONS = [
  { value: 0, label: '全部星级' },
  { value: 3, label: '≥ 3 星' },
  { value: 4, label: '≥ 4 星' },
  { value: 5, label: '仅 5 星' },
];

export default function DashboardPage() {
  const { message } = App.useApp();
  const [stats, setStats] = useState<Stats | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [minStar, setMinStar] = useState(0);

  useEffect(() => {
    apiFetch<Stats>('/api/stats')
      .then(setStats)
      .catch(() => {
        // 统计加载失败时保持空态展示
      });
  }, []);

  const loadRecs = useCallback(async (star: number) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (star > 0) params.set('min_star', String(star));
      const data = await apiFetch<Recommendation[]>(`/api/recommendations?${params.toString()}`);
      setRecs([...data].sort((a, b) => b.star - a.star || b.match_score - a.match_score));
    } catch (e) {
      setRecs([]);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRecs(minStar);
  }, [minStar, loadRecs]);

  const changeFollow = async (rec: Recommendation, status: FollowStatus) => {
    const prev = rec.follow_status;
    setRecs((rs) => rs.map((r) => (r.id === rec.id ? { ...r, follow_status: status } : r)));
    try {
      await apiFetch<{ ok: boolean }>(`/api/follow/${rec.id}`, {
        method: 'POST',
        body: JSON.stringify({ status }),
      });
      message.success('跟进状态已更新');
    } catch (e) {
      setRecs((rs) => rs.map((r) => (r.id === rec.id ? { ...r, follow_status: prev } : r)));
      message.error((e as Error).message);
    }
  };

  const byStatus = stats?.by_status ?? {};
  const statusEntries = Object.entries(byStatus);

  return (
    <AppLayout>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="今日推荐" value={stats?.tenant?.today_recommended ?? '-'} suffix="条" />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="未读通知" value={stats?.tenant?.unread ?? '-'} suffix="条" />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card title="流水线状态" size="small" styles={{ body: { minHeight: 56 } }}>
            {statusEntries.length === 0 ? (
              <Typography.Text type="secondary">暂无数据</Typography.Text>
            ) : (
              <Space size={[4, 4]} wrap>
                {statusEntries.map(([k, v]) => (
                  <Tag key={k}>
                    {pipelineStatusLabel(k)} {v}
                  </Tag>
                ))}
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      <Card
        title="推荐商机"
        extra={
          <Space>
            <Typography.Text type="secondary">最低星级</Typography.Text>
            <Select value={minStar} options={MIN_STAR_OPTIONS} style={{ width: 120 }} onChange={setMinStar} />
          </Space>
        }
      >
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
          </div>
        ) : recs.length === 0 ? (
          <Empty description="暂无推荐商机" />
        ) : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {recs.map((rec) => {
              const hitRisks = RISK_KEYS.filter((k) => rec.risks?.[k]?.hit);
              return (
                <Card key={String(rec.id)} size="small">
                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    <Space size={12} wrap>
                      <Link href={`/projects/${rec.announcement_id}`}>
                        <Typography.Text strong style={{ fontSize: 15, color: '#1677ff' }}>
                          {rec.title}
                        </Typography.Text>
                      </Link>
                      <Rate disabled value={rec.star} style={{ fontSize: 14 }} />
                      <Typography.Text>匹配分 {rec.match_score}</Typography.Text>
                      <Tag color={ADVICE_COLORS[rec.advice] ?? 'default'}>{rec.advice}</Tag>
                    </Space>
                    <Typography.Text type="secondary">
                      地区：{rec.region ?? '-'}　预算：{formatBudget(rec.budget)}　截止：{rec.deadline ?? '-'}
                    </Typography.Text>
                    {rec.summary ? <Typography.Paragraph style={{ marginBottom: 0 }}>{rec.summary}</Typography.Paragraph> : null}
                    {rec.reasons?.length ? (
                      <div>
                        {rec.reasons.map((r, i) => (
                          <div key={i}>
                            <Typography.Text>· {r.point}</Typography.Text>
                            {r.evidence ? (
                              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                                {r.evidence}
                              </Typography.Text>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                    <Space size={8} wrap>
                      {hitRisks.map((k) => {
                        const risk = rec.risks[k]!;
                        return (
                          <Tooltip key={k} title={risk.evidence ?? '无证据说明'}>
                            <Tag color="red">
                              {RISK_LABELS[k]}
                              {risk.severity ? `（${risk.severity}）` : ''}
                            </Tag>
                          </Tooltip>
                        );
                      })}
                      <span>
                        <Typography.Text type="secondary" style={{ marginRight: 8 }}>
                          跟进状态
                        </Typography.Text>
                        <Select
                          size="small"
                          style={{ width: 100 }}
                          value={rec.follow_status}
                          options={FOLLOW_STATUSES.map((s) => ({ value: s, label: s }))}
                          onChange={(v) => changeFollow(rec, v)}
                        />
                      </span>
                    </Space>
                  </Space>
                </Card>
              );
            })}
          </Space>
        )}
      </Card>
    </AppLayout>
  );
}
