import type { Advice, FollowStatus, RiskKey } from './types';

/** 项目结构化十二字段：字段名 → 中文标签（按展示顺序） */
export const FIELD_LABELS: [string, string][] = [
  ['project_name', '项目名称'],
  ['tender_org', '招标单位'],
  ['publish_time', '发布时间'],
  ['bid_deadline', '投标截止'],
  ['budget', '项目预算'],
  ['industry', '所属行业'],
  ['region', '地区'],
  ['product_category', '产品类别'],
  ['service_type', '服务类型'],
  ['contact', '联系方式'],
  ['attachments_info', '附件信息'],
  ['requirements', '招标要求'],
];

/** 风险项 → 中文标签 */
export const RISK_LABELS: Record<RiskKey, string> = {
  brand_restriction: '品牌限制',
  exclusivity: '排他性条件',
  special_qualification: '特殊资质',
  insufficient_budget: '预算不足',
  high_competition: '竞争激烈',
  rejection_risk: '废标风险',
};

export const RISK_KEYS = Object.keys(RISK_LABELS) as RiskKey[];

/** 参与建议 → Tag 颜色 */
export const ADVICE_COLORS: Record<Advice, string> = {
  建议参与: 'green',
  谨慎参与: 'orange',
  不建议参与: 'red',
};

export const FOLLOW_STATUSES: FollowStatus[] = ['待看', '跟进中', '放弃', '已投标'];

/** 流水线状态英文键 → 中文标签（未知键直接展示原值） */
export const PIPELINE_STATUS_LABELS: Record<string, string> = {
  new: '新增',
  pending: '待处理',
  fetched: '已采集',
  crawled: '已采集',
  cleaned: '已清洗',
  parsed: '已解析',
  extracted: '已提取',
  analyzed: '已分析',
  matched: '已匹配',
  recommended: '已推荐',
  notified: '已通知',
  failed: '失败',
};

export function pipelineStatusLabel(key: string): string {
  return PIPELINE_STATUS_LABELS[key] ?? key;
}

/** 预算展示：数字加千分位与货币符号，字符串原样，空值显示 - */
export function formatBudget(budget: string | number | null | undefined): string {
  if (budget === null || budget === undefined || budget === '') return '-';
  if (typeof budget === 'number') return `¥${budget.toLocaleString('zh-CN')}`;
  return budget;
}
