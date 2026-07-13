'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import {
  Alert,
  App,
  Badge,
  Card,
  Col,
  Empty,
  Progress,
  Rate,
  Row,
  Select,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  BellOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  DatabaseOutlined,
  EnvironmentOutlined,
  ExclamationCircleOutlined,
  PayCircleOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch } from '@/lib/api';
import { FOLLOW_STATUSES, RISK_KEYS, RISK_LABELS, formatBudget, pipelineStatusLabel } from '@/lib/labels';
import type { Advice, FollowStatus, Recommendation, Stats } from '@/lib/types';

const MIN_STAR_OPTIONS = [
  { value: 0, label: '全部星级' },
  { value: 3, label: '≥ 3 星' },
  { value: 4, label: '≥ 4 星' },
  { value: 5, label: '仅 5 星' },
];

const ADVICE_TAG: Record<Advice, { color: string; icon: ReactNode }> = {
  建议参与: { color: 'success', icon: <CheckCircleOutlined /> },
  谨慎参与: { color: 'warning', icon: <ExclamationCircleOutlined /> },
  不建议参与: { color: 'error', icon: <CloseCircleOutlined /> },
};

/** 「今日重点」入选门槛：高星（≥4）且 AI 建议参与，最多展示前 HERO_MAX 条，其余降级为速览行 */
const HERO_MIN_STAR = 4;
const HERO_MAX = 3;
const isHero = (r: Recommendation) => r.star >= HERO_MIN_STAR && r.advice === '建议参与';

/** 匹配分圆环颜色：>=80 绿、60-79 品牌蓝、<60 灰 */
function scoreColor(score: number): string {
  if (score >= 80) return '#52C41A';
  if (score >= 60) return '#2F54EB';
  return '#BFBFBF';
}

/** 流水线分段条：单一品牌色系由浅到深 */
const PIPELINE_RAMP = ['#E6EDFC', '#C2D2F8', '#9AB3F2', '#7092EC', '#4A70E8', '#2F54EB'];

function StatTile({
  label,
  value,
  helper,
  icon,
  iconBg,
  iconColor,
}: {
  label: string;
  value: string | number;
  helper: string;
  icon: ReactNode;
  iconBg: string;
  iconColor: string;
}) {
  return (
    <Card className="compass-card" styles={{ body: { padding: '20px 24px' } }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: '50%',
            background: iconBg,
            color: iconColor,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 18,
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, color: 'rgba(0, 0, 0, 0.45)' }}>{label}</div>
          <div style={{ fontSize: 30, fontWeight: 600, color: 'rgba(0, 0, 0, 0.88)', lineHeight: 1.25 }}>{value}</div>
          <div style={{ fontSize: 12, color: 'rgba(0, 0, 0, 0.35)' }}>{helper}</div>
        </div>
      </div>
    </Card>
  );
}

function PipelineBar({ byStatus }: { byStatus: Record<string, number> }) {
  const entries = Object.entries(byStatus);
  if (entries.length === 0) {
    return <Typography.Text type="secondary">暂无流水线数据，采集任务运行后将自动出现</Typography.Text>;
  }
  const k = entries.length;
  return (
    <div className="pipeline-bar">
      {entries.map(([status, count], i) => {
        const idx = k === 1 ? PIPELINE_RAMP.length - 1 : Math.round((i * (PIPELINE_RAMP.length - 1)) / (k - 1));
        const dark = idx >= 3;
        return (
          <div
            key={status}
            className="pipeline-seg"
            style={{
              flexGrow: Math.max(count, 1),
              flexBasis: 0,
              background: PIPELINE_RAMP[idx],
              color: dark ? '#fff' : 'rgba(0, 0, 0, 0.75)',
            }}
          >
            {pipelineStatusLabel(status)} {count}
          </div>
        );
      })}
    </div>
  );
}

function RecommendationCard({
  rec,
  onFollowChange,
}: {
  rec: Recommendation;
  onFollowChange: (rec: Recommendation, status: FollowStatus) => void;
}) {
  const advice = ADVICE_TAG[rec.advice];
  const hitRisks = RISK_KEYS.filter((k) => rec.risks?.[k]?.hit);

  const card = (
    <Card className="compass-card" styles={{ body: { padding: 20 } }}>
      <div style={{ display: 'flex', gap: 20 }}>
        {/* 左侧主体 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space size={10} wrap style={{ marginBottom: 8 }}>
            <Link href={`/projects/${rec.announcement_id}`}>
              <Typography.Text strong style={{ fontSize: 16, color: '#2F54EB' }}>
                {rec.title}
              </Typography.Text>
            </Link>
            {advice ? (
              <Tag color={advice.color} icon={advice.icon}>
                {rec.advice}
              </Tag>
            ) : null}
          </Space>
          <Space size={16} wrap style={{ marginBottom: 10 }}>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              <EnvironmentOutlined style={{ marginRight: 4 }} />
              {rec.region ?? '-'}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              <PayCircleOutlined style={{ marginRight: 4 }} />
              {formatBudget(rec.budget)}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              <ClockCircleOutlined style={{ marginRight: 4 }} />
              {rec.deadline ?? '-'}
            </Typography.Text>
          </Space>
          {rec.summary ? (
            <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 10 }}>
              {rec.summary}
            </Typography.Paragraph>
          ) : null}
          {rec.reasons?.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
              {rec.reasons.map((r, i) => (
                <div key={i} className="reason-chip">
                  {r.point}
                  {r.evidence ? (
                    <span style={{ color: 'rgba(0, 0, 0, 0.4)', marginLeft: 8, fontSize: 12 }}>{r.evidence}</span>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
          {hitRisks.length ? (
            <Space size={[6, 6]} wrap>
              {hitRisks.map((k) => {
                const risk = rec.risks[k]!;
                const high = risk.severity === '高' || risk.severity === null;
                return (
                  <Tooltip key={k} title={risk.evidence ?? '无证据说明'}>
                    <Tag color={high ? 'error' : 'warning'} icon={<WarningOutlined />}>
                      {RISK_LABELS[k]}
                      {risk.severity ? `（${risk.severity}）` : ''}
                    </Tag>
                  </Tooltip>
                );
              })}
            </Space>
          ) : null}
        </div>
        {/* 右侧评分区 */}
        <div
          style={{
            width: 130,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
          }}
        >
          <div style={{ textAlign: 'center' }}>
            <Progress
              type="circle"
              size={64}
              percent={rec.match_score}
              strokeColor={scoreColor(rec.match_score)}
              format={(p) => <span style={{ fontSize: 16, color: 'rgba(0, 0, 0, 0.88)' }}>{p}</span>}
            />
            <div style={{ fontSize: 12, color: 'rgba(0, 0, 0, 0.45)', marginTop: 4 }}>匹配分</div>
          </div>
          <Rate disabled value={rec.star} style={{ fontSize: 13 }} />
          <Select
            size="small"
            style={{ width: 110 }}
            value={rec.follow_status}
            options={FOLLOW_STATUSES.map((s) => ({ value: s, label: s }))}
            onChange={(v) => onFollowChange(rec, v)}
          />
        </div>
      </div>
    </Card>
  );

  return rec.star === 5 ? (
    <Badge.Ribbon text="TOP" color="#FAAD14">
      {card}
    </Badge.Ribbon>
  ) : (
    card
  );
}

/** 分区小标题：标题 + 计数 + 可选说明 + 右侧分隔线 */
function SectionLabel({ text, count, hint }: { text: string; count: number; hint?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
      <span style={{ fontSize: 14, fontWeight: 600, color: 'rgba(0, 0, 0, 0.88)' }}>{text}</span>
      <span style={{ fontSize: 13, color: 'rgba(0, 0, 0, 0.35)', fontVariantNumeric: 'tabular-nums' }}>{count}</span>
      {hint ? <span style={{ fontSize: 12, color: 'rgba(0, 0, 0, 0.35)' }}>· {hint}</span> : null}
      <span style={{ flex: 1, height: 1, background: 'rgba(0, 0, 0, 0.06)' }} />
    </div>
  );
}

/** 速览行：长尾商机一行一条——匹配分 + 星级 + 标题/关键信息 + 风险 + 建议 + 跟进 */
function CompactRecRow({
  rec,
  onFollowChange,
}: {
  rec: Recommendation;
  onFollowChange: (rec: Recommendation, status: FollowStatus) => void;
}) {
  const advice = ADVICE_TAG[rec.advice];
  const hitRisks = RISK_KEYS.filter((k) => rec.risks?.[k]?.hit);
  return (
    <div className="rec-crow">
      <span
        style={{
          width: 34,
          flexShrink: 0,
          textAlign: 'center',
          fontSize: 16,
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
          color: scoreColor(rec.match_score),
        }}
      >
        {rec.match_score}
      </span>
      <Rate disabled value={rec.star} style={{ fontSize: 11, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <Link
          href={`/projects/${rec.announcement_id}`}
          style={{
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            color: '#2F54EB',
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          {rec.title}
        </Link>
        <span style={{ flexShrink: 0, color: 'rgba(0, 0, 0, 0.4)', fontSize: 12, whiteSpace: 'nowrap' }}>
          {rec.region ?? '-'} · {formatBudget(rec.budget)} · 截止 {rec.deadline ?? '-'}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        {hitRisks.length ? (
          <Tooltip title={hitRisks.map((k) => RISK_LABELS[k]).join('、')}>
            <Tag color="warning" icon={<WarningOutlined />} style={{ marginInlineEnd: 0 }}>
              {hitRisks.length}
            </Tag>
          </Tooltip>
        ) : null}
        {advice ? (
          <Tag color={advice.color} style={{ marginInlineEnd: 0 }}>
            {rec.advice}
          </Tag>
        ) : null}
        <Select
          size="small"
          style={{ width: 96 }}
          value={rec.follow_status}
          options={FOLLOW_STATUSES.map((s) => ({ value: s, label: s }))}
          onChange={(v) => onFollowChange(rec, v)}
        />
      </div>
    </div>
  );
}

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

  // 分层聚焦：recs 已按 (星级, 匹配分) 降序 → 取前 HERO_MAX 条高价值商机为「今日重点」，其余降级速览行
  const { heroes, rest } = useMemo(() => {
    const picked = recs.filter(isHero).slice(0, HERO_MAX);
    const heroIds = new Set(picked.map((r) => r.id));
    return { heroes: picked, rest: recs.filter((r) => !heroIds.has(r.id)) };
  }, [recs]);

  const byStatus = stats?.by_status ?? {};
  const totalAnnouncements = Object.values(byStatus).reduce((a, b) => a + b, 0);

  return (
    <AppLayout title="商机工作台" subtitle="AI 为您主动发现并评估的招标商机">
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <StatTile
            label="今日推荐"
            value={stats?.tenant?.today_recommended ?? '—'}
            helper="AI 匹配企业画像后自动生成"
            icon={<ThunderboltOutlined />}
            iconBg="rgba(47, 84, 235, 0.08)"
            iconColor="#2F54EB"
          />
        </Col>
        <Col xs={24} sm={8}>
          <StatTile
            label="未读通知"
            value={stats?.tenant?.unread ?? '—'}
            helper="高星商机将第一时间提醒"
            icon={<BellOutlined />}
            iconBg="rgba(250, 173, 20, 0.12)"
            iconColor="#D48806"
          />
        </Col>
        <Col xs={24} sm={8}>
          <StatTile
            label="公告总量"
            value={stats ? totalAnnouncements : '—'}
            helper="全流水线累计采集公告数"
            icon={<DatabaseOutlined />}
            iconBg="rgba(47, 84, 235, 0.08)"
            iconColor="#2F54EB"
          />
        </Col>
      </Row>

      <Card className="compass-card" title="处理流水线" size="small" style={{ marginBottom: 24 }}>
        <PipelineBar byStatus={byStatus} />
      </Card>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 18,
        }}
      >
        <span style={{ fontSize: 17, fontWeight: 600, color: 'rgba(0, 0, 0, 0.88)' }}>推荐商机</span>
        <Space>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            最低星级
          </Typography.Text>
          <Select value={minStar} options={MIN_STAR_OPTIONS} style={{ width: 120 }} onChange={setMinStar} />
        </Space>
      </div>

      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}

      {loading ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Card className="compass-card">
            <Skeleton active paragraph={{ rows: 3 }} />
          </Card>
          <Card className="compass-card">
            <Skeleton active paragraph={{ rows: 3 }} />
          </Card>
        </Space>
      ) : recs.length === 0 ? (
        <Card className="compass-card">
          <Empty description="暂无推荐商机，采集与匹配运行后将自动出现" />
        </Card>
      ) : (
        <>
          {heroes.length > 0 ? (
            <div style={{ marginBottom: rest.length > 0 ? 24 : 0 }}>
              <SectionLabel text="🎯 今日重点" count={heroes.length} hint="AI 建议参与 · 高匹配，优先跟进" />
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                {heroes.map((rec) => (
                  <RecommendationCard key={String(rec.id)} rec={rec} onFollowChange={changeFollow} />
                ))}
              </Space>
            </div>
          ) : null}
          {rest.length > 0 ? (
            <div>
              <SectionLabel text="其余商机" count={rest.length} hint="一行一条，快速扫读" />
              <div className="rec-compact-list">
                {rest.map((rec) => (
                  <CompactRecRow key={String(rec.id)} rec={rec} onFollowChange={changeFollow} />
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}
    </AppLayout>
  );
}
