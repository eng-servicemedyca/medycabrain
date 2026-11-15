import { apiClient } from "./client";
import type { Paginated } from "./types";

export interface KnowledgeDoc {
  id: number;
  source_type: string;
  source_url: string;
  title: string;
  author: string;
  published_at: string | null;
  summary_it: string;
  topics: string[];
  primary_topic?: string;
  owner_type?: "owned" | "competitor";
  language?: string;
  source?: { id: number; name: string; owner_type: string } | null;
  enrich_status: string;
  created_at: string;
}

export interface KnowledgeDocDetail extends KnowledgeDoc {
  content_md: string;
  embed_status: string;
  updated_at: string;
  arguments?: { id: number; text_it: string; quote: string }[];
}

export async function fetchKnowledgeDoc(id: number): Promise<KnowledgeDocDetail> {
  const { data } = await apiClient.get<KnowledgeDocDetail>(`/knowledge/documents/${id}/`);
  return data;
}

/** One page of the article list. The page used to take the first 100 and stop:
 *  903 competitor articles showed as 100, with nothing saying so. */
export async function fetchKnowledgeDocs(
  search: string | undefined,
  scope: "medyca" | "competitor",
  page = 1
): Promise<Paginated<KnowledgeDoc>> {
  const { data } = await apiClient.get<Paginated<KnowledgeDoc>>("/knowledge/documents/", {
    params: { search: search || undefined, scope, page, page_size: 48 },
  });
  return data;
}

/** The articles of one cluster (its own scope is implied by the cluster). */
export async function fetchClusterDocs(
  clusterId: number,
  page = 1
): Promise<Paginated<KnowledgeDoc>> {
  const { data } = await apiClient.get<Paginated<KnowledgeDoc>>("/knowledge/documents/", {
    params: { cluster: clusterId, page, page_size: 30 },
  });
  return data;
}
