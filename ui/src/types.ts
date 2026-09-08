export type Values = Record<string, string | number | boolean | string[]>;
export interface Option {
  key: string;
  label?: string;
  type?: string;
  kind?: string;
  minimum?: number;
  maximum?: number;
  default?: string | number | boolean | string[];
  min?: number;
  max?: number;
  step?: number;
  options?: (string | { value: string; label: string })[];
  choices?: (string | { value: string; label: string })[];
}
export interface Champion {
  name: string;
  icon: string;
  engine_registration: string | null;
  resource?: string;
  rank_defaults_by_level?: Record<string, Record<string, number>>;
  abilities: Record<
    string,
    {
      name: string;
      icon?: string;
      description?: string;
      rank_values?: { label: string; values: string[] }[];
    }
  >;
}
export interface ShopRelation {
  id: number;
  name: string | null;
  icon: string | null;
  price: number | null;
  catalog_available: boolean;
}
export interface Item {
  id: number;
  name: string;
  icon: string;
  price: number;
  tier: number;
  rank?: string[] | null;
  shop_tags?: string[];
  effects?: {
    kind: "passive" | "active";
    name: string | null;
    text: string;
    text_format: "wikitext";
  }[];
  builds_from?: ShopRelation[];
  builds_into?: ShopRelation[];
  ap: number;
  ad: number;
  hp: number;
  armor: number;
  mr: number;
  haste: number;
  mana?: number;
  manaRegen?: number;
  attackSpeed?: number;
  crit?: number;
  critDamage?: number;
  pen?: number;
  percentPen?: number;
  lethality?: number;
  percentArmorPen?: number;
  lifesteal?: number;
  omnivamp?: number;
  healAndShieldPower?: number;
  healthRegen?: number;
  moveSpeed?: number;
  moveSpeedPercent?: number;
  tenacity?: number;
  model_coverage?: { status?: string; optimizer_eligible?: boolean };
}
export interface Rune {
  icon?: string;
  name: string;
  path: string;
  row: number;
  implemented: boolean;
  options: Option[];
}
export interface Config {
  default_target: Record<string, number>;
  fight_defaults: { duration_seconds: number };
  input_limits: Record<string, number[]>;
  champion_options: Record<
    string,
    {
      options: Option[];
      assumptions: string[];
      sources: { label: string; url?: string; revision_id?: number }[];
    }
  >;
  item_options: Record<
    string,
    { options: Record<string, Omit<Option, "key">> }
  >;
  keystone_options: Record<
    string,
    { options: Record<string, Omit<Option, "key">> }
  >;
  runes: Rune[];
  keystones: Rune[];
  rune_shards: {
    row: number;
    name: string;
    options: { name: string; implemented: boolean }[];
  }[];
  data_snapshot: {
    patch: { public?: string; client?: string };
    fetched_at?: string;
  };
  domain_contract: {
    role_quest: {
      roles: string[];
      level_cap: DomainValue;
      inventory_capacity: DomainValue;
      boots_tier: DomainValue;
    };
    rank_allocation: { by_champion: Record<string, string> };
  };
}
export interface DomainValue {
  default: number;
  by_role: Record<string, { complete: number; incomplete: number }>;
}
export interface Build {
  items: (string | null)[];
  boots: string;
  keystone: string;
  keystone_options: Values;
  minor_runes: string[];
  stat_shards: string[];
  item_options: Record<string, Values>;
  rune_options: Record<string, Values>;
}
export interface Result {
  headline_total?: number | null;
  total_damage?: number;
  health_damage?: number;
  shield_absorbed?: number;
  self_healing?: number;
  error?: string;
  timeline_coverage?: {
    complete: boolean;
    note?: string;
    certification?: string;
  };
  notes?: string[];
  breakdown?: Record<
    string,
    {
      name: string;
      total_damage: number;
      total_amount?: number;
      casts?: number;
      count?: number;
      detail?: string;
    }
  >;
  damage_by_type?: Record<string, number>;
  champion_stats?: Record<string, number>;
  cast_timeline?: { time: number; slot: string; name: string }[];
  dispositions?: Record<string, unknown>;
  [key: string]: unknown;
}
export interface Optimization {
  is_certified_best: boolean;
  items?: string[];
  boots?: string;
  selection_certification?: string;
  search_timeline_coverage?: { note?: string; coarse_sources?: string[] };
  timeline_coverage?: { complete: boolean; note?: string };
  total_damage?: number;
  search_guarantee?: string;
  evaluations?: number;
  error?: string;
}
