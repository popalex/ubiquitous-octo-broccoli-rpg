import { templates as baseTemplates, type RoleplayTemplate } from "./templates";

export async function loadExtraTemplates(): Promise<RoleplayTemplate[]> {
  try {
    const res = await fetch("/templates-extra.json");
    if (!res.ok) return [];
    const extra: RoleplayTemplate[] = await res.json();
    if (!Array.isArray(extra)) return [];
    return extra;
  } catch {
    return [];
  }
}

export async function loadAllTemplates(): Promise<RoleplayTemplate[]> {
  const extra = await loadExtraTemplates();
  return [...baseTemplates, ...extra];
}
