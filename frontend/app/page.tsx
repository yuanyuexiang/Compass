'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import {
  Alert,
  App,
  Badge,
  Button,
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
  CloudDownloadOutlined,
  CloseCircleOutlined,
  DatabaseOutlined,
  EnvironmentOutlined,
  ExclamationCircleOutlined,
  PayCircleOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import AppLayout from '@/components/AppLayout';
import { apiFetch, getCachedUser } from '@/lib/api';
import { FOLLOW_STATUSES, RISK_KEYS, RISK_LABELS, formatBudget, pipelineStatusLabel } from '@/lib/labels';
import type { Advice, FollowStatus, Recommendation, Stats, User } from '@/lib/types';

/** 系统健康（GET /api/admin/health，仅平台管理员） */
interface HealthData {
  backlog: Record<string, number>;
  failed_total: number;
  last_24h: { crawled: number; published: number; failed: number };
  llm: {
    consecutive_failures: number;
    ok: boolean;
    last_error: string | null;
    fallback_last: string | null;
    last_success_at: string | null;
  };
  scheduler: { ok: boolean; last_auto_crawl_at: string | null; interval_minutes: number };
  stale_sources: { id: number; name: string; last_run_at: string | null }[];
}

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

const DIMENSION_LABELS: Record<string, string> = {
  business_fit: '主体业务',
  case_evidence: '案例证明',
  product_service: '产品服务',
  qualification: '资质准入',
  delivery_region: '地区履约',
  commercial_preference: '经营偏好',
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

function HealthPanel({ health }: { health: HealthData | null }) {
  if (!health) {
    return (
      <Card className="compass-card" title="系统健康" size="small">
        <Skeleton active paragraph={{ rows: 2 }} />
      </Card>
    );
  }
  return (
    <Card className="compass-card" title="系统健康" size="small">
      <Space size={[24, 10]} wrap align="center">
        <Space size={6}>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>AI 服务</Typography.Text>
          {health.llm.ok ? (
            <Tag icon={<CheckCircleOutlined />} color="green">正常</Tag>
          ) : (
            <Tooltip title={health.llm.last_error ?? ''}>
              <Tag icon={<CloseCircleOutlined />} color="red">
                连续失败 {health.llm.consecutive_failures} 次
              </Tag>
            </Tooltip>
          )}
          {health.llm.fallback_last ? (
            <Tooltip title={health.llm.fallback_last}>
              <Tag icon={<WarningOutlined />} color="orange">启用过备用模型</Tag>
            </Tooltip>
          ) : null}
        </Space>
        <Space size={6}>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>采集调度</Typography.Text>
          {health.scheduler.ok ? (
            <Tag icon={<CheckCircleOutlined />} color="green">正常</Tag>
          ) : (
            <Tag icon={<WarningOutlined />} color="orange">疑似停摆</Tag>
          )}
        </Space>
        <Typography.Text style={{ fontSize: 13 }}>
          24h：采集 {health.last_24h.crawled} · 发布 {health.last_24h.published} · 失败{' '}
          {health.last_24h.failed}
        </Typography.Text>
        {Object.keys(health.backlog).length ? (
          <Space size={6} wrap>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>积压</Typography.Text>
            {Object.entries(health.backlog).map(([s, n]) => (
              <Tag key={s} color="gold">{pipelineStatusLabel(s)} {n}</Tag>
            ))}
          </Space>
        ) : null}
        {health.failed_total ? <Tag color="red">累计失败 {health.failed_total}</Tag> : null}
        {health.stale_sources.length ? (
          <Tooltip title={health.stale_sources.map((s) => s.name).join('、')}>
            <Tag icon={<WarningOutlined />} color="orange">
              {health.stale_sources.length} 个源 48h 无新公告
            </Tag>
          </Tooltip>
        ) : null}
      </Space>
    </Card>
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
          {rec.score_details?.dimensions ? (
            <Space size={[6, 6]} wrap style={{ marginBottom: 10 }}>
              {Object.entries(rec.score_details.dimensions).map(([key, value]) => (
                <Tooltip key={key} title={value.evidence || value.note || '暂无证据说明'}>
                  <Tag>
                    {DIMENSION_LABELS[key] ?? key} {value.score}
                  </Tag>
                </Tooltip>
              ))}
              {rec.score_details.delivery_mode === 'partner' ? <Tag color="gold">需合作参与</Tag> : null}
              {rec.score_details.qualification_status === 'unknown' ? <Tag>资质待确认</Tag> : null}
            </Space>
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
  // 页面按角色整体分叉，角色须在挂载后从 localStorage 解析（undefined = 未解析）——
  // 渲染期直接读会让静态预渲染的 HTML 与客户端首帧不一致，触发 hydration 报错
  const [user, setUser] = useState<User | null>();
  useEffect(() => {
    setUser(getCachedUser<User>() ?? null);
  }, []);
  const resolved = user !== undefined;
  const isPlatform = user?.role === 'platform_admin';
  const isTenantAdmin = user?.role === 'tenant_admin';
  const [stats, setStats] = useState<Stats | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [minStar, setMinStar] = useState(0);

  const [health, setHealth] = useState<HealthData | null>(null);

  useEffect(() => {
    if (!resolved) return;
    apiFetch<Stats>('/api/stats')
      .then((s) => {
        setStats(s);
        if (isPlatform) {
          apiFetch<HealthData>('/api/admin/health').then(setHealth).catch(() => {});
        }
      })
      .catch(() => {
        // 统计加载失败时保持空态展示
      });
  }, [resolved, isPlatform]);

  const loadRecs = useCallback(async (star: number) => {
    if (!resolved || isPlatform) {
      setLoading(false);
      return;
    }
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
  }, [resolved, isPlatform]);

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

  // by_status 仅平台管理员返回，用于运营工作台展示流水线。
  const byStatus = stats?.by_status;

  // 角色未解析：服务端预渲染与客户端首帧都走这里，两侧一致不触发 hydration 告警
  if (!resolved) {
    return (
      <AppLayout title="工作台" subtitle="加载中…">
        <Card className="compass-card">
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      </AppLayout>
    );
  }

  if (isPlatform) {
    return (
      <AppLayout title="运营工作台" subtitle="平台健康、审批、采集与模型运行状态">
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} sm={12} lg={6}>
            <StatTile
              label="待审批租户"
              value={stats?.platform?.pending_tenants ?? '—'}
              helper="企业开通申请"
              icon={<CheckCircleOutlined />}
              iconBg="rgba(47, 84, 235, 0.08)"
              iconColor="#2F54EB"
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <StatTile
              label="待审批数据源"
              value={stats?.platform?.pending_sources ?? '—'}
              helper="租户提交的新源申请"
              icon={<CloudDownloadOutlined />}
              iconBg="rgba(250, 173, 20, 0.12)"
              iconColor="#D48806"
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <StatTile
              label="活跃数据源"
              value={stats?.platform?.active_sources ?? '—'}
              helper="当前参与自动采集"
              icon={<DatabaseOutlined />}
              iconBg="rgba(82, 196, 26, 0.12)"
              iconColor="#389E0D"
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <StatTile
              label="平台用户"
              value={stats?.platform?.users_total ?? '—'}
              helper={`${stats?.platform?.tenants_total ?? '—'} 个业务租户`}
              icon={<BellOutlined />}
              iconBg="rgba(114, 46, 209, 0.10)"
              iconColor="#722ED1"
            />
          </Col>
        </Row>

        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} xl={16}>
            <HealthPanel health={health} />
          </Col>
          <Col xs={24} xl={8}>
            <Card className="compass-card" title="优先处理" size="small">
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                <Link href="/tenants">
                  <Button block type={stats?.platform?.pending_tenants ? 'primary' : 'default'}>
                    审批企业开通
                  </Button>
                </Link>
                <Link href="/sources">
                  <Button block>检查采集源与申请</Button>
                </Link>
                <Link href="/models">
                  <Button block>查看模型服务</Button>
                </Link>
                <Link href="/logs">
                  <Button block>查看运行日志</Button>
                </Link>
              </Space>
            </Card>
          </Col>
        </Row>

        <Card className="compass-card" title="处理流水线" size="small">
          <PipelineBar byStatus={byStatus ?? {}} />
        </Card>
      </AppLayout>
    );
  }

  return (
    <AppLayout
      title={isTenantAdmin ? '企业工作台' : '商机工作台'}
      subtitle={isTenantAdmin ? '企业画像、成员与今日推荐的整体状态' : '待查看、跟进中与高匹配招标商机'}
    >
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
            label="可见公告"
            value={stats?.visible_announcements ?? '—'}
            helper="按你的关注地区与数据源统计"
            icon={<DatabaseOutlined />}
            iconBg="rgba(47, 84, 235, 0.08)"
            iconColor="#2F54EB"
          />
        </Col>
      </Row>

      {isTenantAdmin ? (
        <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
          <Col xs={24} md={8}>
            <Card className="compass-card" size="small" title="画像完整度">
              <Progress percent={stats?.tenant?.profile_completeness ?? 0} />
              <Link href="/profile">完善企业画像</Link>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card className="compass-card" size="small" title="成员与协作">
              <Typography.Title level={3} style={{ marginTop: 0 }}>
                {stats?.tenant?.members_total ?? '—'}
              </Typography.Title>
              <Link href="/members">管理成员账号</Link>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card className="compass-card" size="small" title="订阅范围">
              <Typography.Title level={3} style={{ marginTop: 0 }}>
                {stats?.tenant?.source_scope_all ? '全部源' : `${stats?.tenant?.subscribed_sources ?? 0} 个源`}
              </Typography.Title>
              <Link href="/settings">调整订阅设置</Link>
            </Card>
          </Col>
        </Row>
      ) : null}

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
