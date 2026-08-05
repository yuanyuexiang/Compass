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
  const entries = Object.entries(byStatus).filter(([status]) => status !== 'skipped');
  const skipped = byStatus.skipped ?? 0;
  if (entries.length === 0) {
    return (
      <Space>
        <Typography.Text type="secondary">暂无处理中流水线数据</Typography.Text>
        {skipped ? <Tag>已归档跳过 {skipped}</Tag> : null}
      </Space>
    );
  }
  const colors: Record<string, { bg: string; color: string }> = {
    failed: { bg: '#FFF1F0', color: '#CF1322' },
    cleaned: { bg: '#FFF7E6', color: '#AD6800' },
    attachments_parsed: { bg: '#FFF7E6', color: '#AD6800' },
    ai_extracted: { bg: '#E6F4FF', color: '#0958D9' },
    embedded: { bg: '#E6F4FF', color: '#0958D9' },
    published: { bg: '#E6FFFB', color: '#08979C' },
  };
  return (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <div className="pipeline-bar">
        {entries.map(([status, count]) => {
          const tone = colors[status] ?? { bg: '#EEF2FF', color: '#2F54EB' };
          return (
            <div
              key={status}
              className="pipeline-seg"
              style={{
                flexGrow: Math.max(count, 1),
                flexBasis: 0,
                background: tone.bg,
                color: tone.color,
              }}
            >
              {pipelineStatusLabel(status)} {count}
            </div>
          );
        })}
      </div>
      <Space size={8} wrap>
        {skipped ? <Tag>已归档跳过 {skipped}</Tag> : null}
        {byStatus.failed ? <Tag color="red">失败 {byStatus.failed}</Tag> : null}
      </Space>
    </Space>
  );
}

function HealthCell({
  title,
  status,
  statusColor,
  children,
}: {
  title: string;
  status: string;
  statusColor: string;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        padding: 16,
        border: '1px solid #F0F0F0',
        borderRadius: 8,
        minHeight: 132,
        background: '#fff',
      }}
    >
      <Space
        align="center"
        style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}
      >
        <Typography.Text strong>{title}</Typography.Text>
        <Tag color={statusColor}>{status}</Tag>
      </Space>
      {children}
    </div>
  );
}

function DiagnosisCard({
  title,
  description,
  href,
  tag,
  tone = 'blue',
}: {
  title: string;
  description: string;
  href: string;
  tag: string;
  tone?: string;
}) {
  return (
    <Link href={href}>
      <div
        style={{
          height: '100%',
          padding: 14,
          border: '1px solid #F0F0F0',
          borderRadius: 8,
          background: '#fff',
          color: 'rgba(0, 0, 0, 0.88)',
        }}
      >
        <Space align="center" style={{ width: '100%', justifyContent: 'space-between' }}>
          <Typography.Text strong>{title}</Typography.Text>
          <Tag color={tone} style={{ marginInlineEnd: 0 }}>{tag}</Tag>
        </Space>
        <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 13 }}>
          {description}
        </Typography.Paragraph>
      </div>
    </Link>
  );
}

function OperationsAdvice({ health }: { health: HealthData }) {
  const items: Array<{
    title: string;
    description: string;
    href: string;
    tag: string;
    tone?: string;
  }> = [];
  const backlogTotal = Object.values(health.backlog).reduce((a, b) => a + b, 0);
  if (!health.llm.ok) {
    items.push({
      title: '排查模型服务',
      description: '优先检查 extract 场景模型、供应商余额和 API Key；恢复后观察待提取队列是否继续消化。',
      href: '/models',
      tag: `失败 ${health.llm.consecutive_failures}`,
      tone: 'red',
    });
  }
  if (!health.scheduler.ok) {
    items.push({
      title: '检查采集调度',
      description: '确认 beat/worker 正常运行，并检查白天自动采集窗口与最近一次自动采集时间。',
      href: '/logs',
      tag: '调度',
      tone: 'orange',
    });
  }
  if (health.stale_sources.length) {
    items.push({
      title: '处理异常采集源',
      description: '进入采集管理查看源站最近运行时间；必要时手动测试采集或调整选择器。',
      href: '/sources',
      tag: `${health.stale_sources.length} 个源`,
      tone: 'orange',
    });
  }
  if (backlogTotal) {
    items.push({
      title: '观察积压消化',
      description: '模型恢复后，关注 backlog tick 是否持续派发；旧公告可按时效策略归档跳过。',
      href: '/logs',
      tag: `${backlogTotal} 待处理`,
      tone: 'gold',
    });
  }
  if (!items.length) {
    items.push(
      {
        title: '查看运行日志',
        description: '系统暂无明显异常，建议定期检查采集轮次、模型备用切换和健康告警记录。',
        href: '/logs',
        tag: '巡检',
      },
      {
        title: '复核模型用量',
        description: '关注不同场景的调用量和 token 消耗，及时发现异常放量或配置不合理。',
        href: '/models',
        tag: '成本',
      },
    );
  }
  return (
    <div style={{ marginTop: 12 }}>
      <Typography.Text strong>异常诊断</Typography.Text>
      <Row gutter={[12, 12]} style={{ marginTop: 10 }}>
        {items.slice(0, 4).map((item) => (
          <Col xs={24} md={12} key={item.title}>
            <DiagnosisCard {...item} />
          </Col>
        ))}
      </Row>
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
  const backlogTotal = Object.values(health.backlog).reduce((a, b) => a + b, 0);
  return (
    <Card className="compass-card" title="系统健康" size="small">
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={8}>
          <HealthCell
            title="AI 服务"
            status={health.llm.ok ? '正常' : '异常'}
            statusColor={health.llm.ok ? 'green' : 'red'}
          >
            <Typography.Title level={4} style={{ margin: 0 }}>
              {health.llm.ok ? '运行中' : `失败 ${health.llm.consecutive_failures} 次`}
            </Typography.Title>
            <Typography.Paragraph
              type="secondary"
              ellipsis={{ rows: 2 }}
              style={{ margin: '8px 0 0' }}
            >
              {health.llm.ok
                ? `最近成功：${health.llm.last_success_at ?? '暂无记录'}`
                : health.llm.last_error ?? '暂无错误详情'}
            </Typography.Paragraph>
            {health.llm.fallback_last ? <Tag color="orange">已触发备用模型</Tag> : null}
          </HealthCell>
        </Col>
        <Col xs={24} lg={8}>
          <HealthCell
            title="采集调度"
            status={health.scheduler.ok ? '正常' : '疑似停摆'}
            statusColor={health.scheduler.ok ? 'green' : 'orange'}
          >
            <Typography.Title level={4} style={{ margin: 0 }}>
              {health.scheduler.interval_minutes} 分钟
            </Typography.Title>
            <Typography.Text type="secondary">
              上次自动采集：{health.scheduler.last_auto_crawl_at ?? '暂无记录'}
            </Typography.Text>
            <div style={{ marginTop: 8 }}>
              {health.stale_sources.length ? (
                <Tooltip title={health.stale_sources.map((s) => s.name).join('、')}>
                  <Tag color="orange">{health.stale_sources.length} 个源 48h 无新公告</Tag>
                </Tooltip>
              ) : (
                <Tag color="green">采集源活跃</Tag>
              )}
            </div>
          </HealthCell>
        </Col>
        <Col xs={24} lg={8}>
          <HealthCell
            title="流水线积压"
            status={backlogTotal || health.failed_total ? '需关注' : '正常'}
            statusColor={backlogTotal || health.failed_total ? 'gold' : 'green'}
          >
            <Typography.Title level={4} style={{ margin: 0 }}>
              {backlogTotal} 条待处理
            </Typography.Title>
            <Space size={[6, 6]} wrap style={{ marginTop: 8 }}>
              {Object.entries(health.backlog).map(([s, n]) => (
                <Tag key={s} color="gold">{pipelineStatusLabel(s)} {n}</Tag>
              ))}
              {health.failed_total ? (
                <Tag color="red">累计失败 {health.failed_total}</Tag>
              ) : null}
              {!backlogTotal && !health.failed_total ? (
                <Tag color="green">无明显积压</Tag>
              ) : null}
            </Space>
          </HealthCell>
        </Col>
      </Row>
      <OperationsAdvice health={health} />
    </Card>
  );
}

function PlatformStatusBanner({ stats, health }: { stats: Stats | null; health: HealthData | null }) {
  const problems: string[] = [];
  if (health && !health.llm.ok) problems.push(`AI 连续失败 ${health.llm.consecutive_failures} 次`);
  if (health && !health.scheduler.ok) problems.push('采集疑似停摆');
  if (health?.stale_sources.length) problems.push(`${health.stale_sources.length} 个源 48h 无新公告`);
  if (stats?.platform?.pending_tenants) problems.push(`${stats.platform.pending_tenants} 个企业待审批`);
  if (stats?.platform?.pending_sources) problems.push(`${stats.platform.pending_sources} 个数据源待审批`);
  const abnormal = problems.length > 0;
  return (
    <Alert
      type={abnormal ? 'warning' : 'success'}
      showIcon
      style={{ marginBottom: 16 }}
      message={abnormal ? `需要关注：${problems.join(' · ')}` : '系统运行正常'}
      description={
        health
          ? `24h：采集 ${health.last_24h.crawled} · 发布 ${health.last_24h.published} · 失败 ${health.last_24h.failed}`
          : '正在读取系统健康状态'
      }
    />
  );
}

function TodoQueue({ stats, health }: { stats: Stats | null; health: HealthData | null }) {
  const items = [
    { label: '企业开通审批', count: stats?.platform?.pending_tenants ?? 0, href: '/tenants', tone: 'blue' },
    { label: '数据源审批', count: stats?.platform?.pending_sources ?? 0, href: '/sources', tone: 'orange' },
    { label: '异常采集源', count: health?.stale_sources.length ?? 0, href: '/sources', tone: 'orange' },
    { label: '模型连续失败', count: health?.llm.ok ? 0 : health?.llm.consecutive_failures ?? 0, href: '/models', tone: 'red' },
    { label: '公告累计失败', count: health?.failed_total ?? 0, href: '/logs', tone: 'red' },
  ];
  return (
    <Card className="compass-card" title="待办队列" size="small">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        {items.map((item) => (
          <Link key={item.label} href={item.href}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 12px',
                border: '1px solid #F0F0F0',
                borderRadius: 8,
                color: 'rgba(0, 0, 0, 0.88)',
                background: item.count ? '#FAFAFA' : '#fff',
              }}
            >
              <Typography.Text>{item.label}</Typography.Text>
              <Tag color={item.count ? item.tone : 'default'} style={{ marginInlineEnd: 0 }}>
                {item.count}
              </Tag>
            </div>
          </Link>
        ))}
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
        <PlatformStatusBanner stats={stats} health={health} />
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} xl={16}>
            <HealthPanel health={health} />
          </Col>
          <Col xs={24} xl={8}>
            <TodoQueue stats={stats} health={health} />
          </Col>
        </Row>

        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} sm={12} lg={6}>
            <StatTile
              label="今日采集"
              value={health?.last_24h.crawled ?? '—'}
              helper="过去 24 小时新增公告"
              icon={<CloudDownloadOutlined />}
              iconBg="rgba(47, 84, 235, 0.08)"
              iconColor="#2F54EB"
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <StatTile
              label="今日发布"
              value={health?.last_24h.published ?? '—'}
              helper="已进入可检索与匹配"
              icon={<CheckCircleOutlined />}
              iconBg="rgba(82, 196, 26, 0.12)"
              iconColor="#389E0D"
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <StatTile
              label="活跃数据源"
              value={stats?.platform?.active_sources ?? '—'}
              helper="当前参与自动采集"
              icon={<DatabaseOutlined />}
              iconBg="rgba(250, 173, 20, 0.12)"
              iconColor="#D48806"
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <StatTile
              label="活跃租户"
              value={stats?.platform?.tenants_total ?? '—'}
              helper={`${stats?.platform?.users_total ?? '—'} 个平台用户`}
              icon={<BellOutlined />}
              iconBg="rgba(114, 46, 209, 0.10)"
              iconColor="#722ED1"
            />
          </Col>
        </Row>

        <Card className="compass-card" title="流水线分布" size="small">
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
