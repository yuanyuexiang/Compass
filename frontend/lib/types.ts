// 与后端 API 契约对应的类型定义

export interface User {
  id: number | string;
  username: string;
  role: string;
  tenant_id: number | string;
  tenant_name: string;
}

export interface LoginResponse {
  access_token: string;
  user: User;
}

export interface Stats {
  by_status: Record<string, number>;
  tenant?: {
    today_recommended: number;
    unread: number;
  };
}

export type Advice = '建议参与' | '谨慎参与' | '不建议参与';
export type FollowStatus = '待看' | '跟进中' | '放弃' | '已投标';
export type Severity = '高' | '中' | '低';

export type RiskKey =
  | 'brand_restriction'
  | 'exclusivity'
  | 'special_qualification'
  | 'insufficient_budget'
  | 'high_competition'
  | 'rejection_risk';

export interface RiskItem {
  hit: boolean;
  evidence: string | null;
  severity: Severity | null;
}

export interface Reason {
  point: string;
  evidence: string;
}

export interface Recommendation {
  id: number | string;
  project_id: number | string;
  announcement_id: number | string;
  title: string;
  url: string;
  region: string | null;
  budget: string | number | null;
  deadline: string | null;
  star: number;
  match_score: number;
  advice: Advice;
  reasons: Reason[];
  risks: Partial<Record<RiskKey, RiskItem>>;
  summary: string | null;
  follow_status: FollowStatus;
  created_at: string;
}

export interface AnnouncementItem {
  id: number | string;
  title: string;
  url: string;
  ann_type: string | null;
  region: string | null;
  buyer: string | null;
  publish_time: string | null;
  status: string | null;
  summary?: string | null;
}

export interface AnnouncementList {
  items: AnnouncementItem[];
  total: number;
}

export interface NlSearchResult {
  filters: Record<string, unknown>;
  items: AnnouncementItem[];
  total: number;
}

export interface FieldValue {
  value: string | null;
  evidence: string | null;
  confidence: number;
}

export interface AttachmentItem {
  filename: string;
  status: string;
  needs_ocr: boolean;
}

export interface ProjectDetail {
  announcement: {
    id: number | string;
    title: string;
    url: string;
    publish_time: string | null;
    region: string | null;
    buyer: string | null;
    clean_text: string | null;
  };
  project: {
    fields: Record<string, FieldValue>;
    category: { main: string | null; sub: string | null } | null;
    summary: string | null;
  } | null;
  attachments: AttachmentItem[];
}

export interface ProfileData {
  name: string;
  description: string;
  products: string[];
  services: string[];
  industries: string[];
  regions: string[];
  certifications: string[];
  brands: string[];
  cases_text: string;
  filter: {
    regions: string[];
    min_budget: number | null;
  };
}

export interface EmailChannel {
  enabled: boolean;
  address: string;
}

export interface WebhookChannel {
  enabled: boolean;
  webhook: string;
}

export interface SubscriptionData {
  min_star: number;
  immediate: boolean;
  daily_digest: boolean;
  channels: {
    email: EmailChannel;
    wecom: WebhookChannel;
    dingtalk: WebhookChannel;
    feishu: WebhookChannel;
  };
}

export interface NotificationItem {
  id: number | string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
}
