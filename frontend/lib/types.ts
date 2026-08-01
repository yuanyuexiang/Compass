// 与后端 API 契约对应的类型定义

export interface User {
  id: number | string;
  username: string;
  role: string;
  email?: string | null;
  tenant_id: number | string;
  tenant_name: string;
}

export interface TenantAdminItem {
  id: number;
  name: string;
  status: 'pending' | 'active' | 'disabled' | string;
  status_label: string;
  enabled: boolean;
  user_count: number;
  has_profile: boolean;
  admin_username: string | null;
  admin_email: string | null;
  created_at: string | null;
  is_self: boolean;
}

export interface MemberItem {
  id: number;
  username: string;
  role: string;
  role_label: string;
  email: string | null;
  enabled: boolean;
  created_at: string | null;
}

export interface UsageItem {
  tenant_id: number | null;
  tenant_name: string;
  scene: string;
  calls: number;
  total_tokens: number;
}

export interface LoginResponse {
  access_token: string;
  user: User;
}

export interface Stats {
  /** 流水线明细：仅平台管理员返回 */
  by_status?: Record<string, number>;
  /** 租户可见公告数（画像地区 + 关注数据源口径，与商机查询一致） */
  visible_announcements?: number;
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
  score_details?: {
    dimensions?: Record<string, { score: number; evidence?: string | null; note?: string }>;
    fit_level?: 'high' | 'medium' | 'partial' | 'none';
    qualification_status?: 'satisfied' | 'unknown' | 'missing';
    delivery_mode?: 'independent' | 'partner' | 'unsuitable';
    vector_similarity?: number | null;
  };
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
  region_scope?: string[];
}

export interface NlSearchResult {
  filters: Record<string, unknown>;
  items: AnnouncementItem[];
  total: number;
  region_scope?: string[];
  // 'quota' = 当日 AI 搜索次数用完，已降级为关键词搜索
  degraded?: string | null;
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
  /** 当前生效版本的更新时间（只读，后端返回） */
  updated_at?: string | null;
}

/** AI 生成画像草稿（POST /api/profile/suggest）：draft 预填表单，不含 filter（经营决策手填） */
export interface SuggestSourceGroup {
  label: string;
  items: { title: string | null; link: string | null }[];
}

export interface ProfileSuggestResult {
  draft: Partial<ProfileData>;
  sources: string[];
  /** 按信源分组（官网/中标记录/招聘/网页），新版后端返回 */
  source_groups?: SuggestSourceGroup[];
  confidence: 'high' | 'medium' | 'low' | string;
  note: string;
}

export type ProfileMaterialStatus =
  | 'parsed'
  | 'extracting'
  | 'extracted'
  | 'no_facts'
  | 'extract_failed'
  | 'needs_ocr';

export interface ProfileMaterialItem {
  id: number;
  filename: string;
  source_type: string;
  document_type: string;
  content_type: string | null;
  parse_status: ProfileMaterialStatus | string;
  needs_ocr: boolean;
  error: string | null;
  fact_count: number;
  created_at: string;
}

export interface ProjectCaseFactValue {
  project_name: string;
  company_role: 'winner' | 'supplier' | 'consortium_member' | 'candidate' | 'mentioned' | 'unknown';
  customer: string | null;
  amount_yuan: number | null;
  region: string | null;
  awarded_at: string | null;
  services: string[];
}

export interface ProfileFactItem {
  id: number;
  fact_type: 'project_case' | string;
  value: ProjectCaseFactValue;
  confidence: number;
  source_strength: string;
  status: 'pending' | 'confirmed' | 'rejected';
  evidence: {
    material_id: number;
    filename: string;
    page: number | null;
    quote: string;
  } | null;
  created_at: string;
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
  /** 关注的数据源 id 列表；空 = 全部数据源 */
  source_ids?: number[];
}

export interface SourceOption {
  id: number;
  display_name: string;
  enabled: boolean;
}

export interface SourceRequestItem {
  id: number;
  display_name: string;
  url: string;
  note: string;
  status: 'pending' | 'active' | 'rejected';
  reject_reason: string | null;
  created_at: string | null;
}

export interface NotificationItem {
  id: number | string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
  announcement_id: number | string | null;
}
