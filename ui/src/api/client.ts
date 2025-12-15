// API client for NoteFlow v2

import type { Job, PipelineStats, ProcessorInfo, Artifact } from "../types";

const API_BASE = "http://localhost:8000/api";

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// Jobs API
export async function listJobs(status?: string): Promise<Job[]> {
  const url = status ? `${API_BASE}/jobs?status=${status}` : `${API_BASE}/jobs`;
  return fetchJson<Job[]>(url);
}

export async function getJob(jobId: string): Promise<Job> {
  return fetchJson<Job>(`${API_BASE}/jobs/${jobId}`);
}

export async function createJob(params: {
  source_type: string;
  source_name: string;
  source_path?: string;
  source_url?: string;
  data?: Record<string, unknown>;
  config?: Record<string, unknown>;
  tags?: string[];
  priority?: number;
}): Promise<Job> {
  return fetchJson<Job>(`${API_BASE}/jobs`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function deleteJob(jobId: string, revert = true): Promise<void> {
  await fetchJson(`${API_BASE}/jobs/${jobId}?revert=${revert}`, {
    method: "DELETE",
  });
}

export async function processJob(jobId: string): Promise<Job> {
  return fetchJson<Job>(`${API_BASE}/jobs/${jobId}/process`, {
    method: "POST",
  });
}

export async function resumeJob(
  jobId: string,
  userInput: Record<string, unknown>
): Promise<Job> {
  return fetchJson<Job>(`${API_BASE}/jobs/${jobId}/resume`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export async function cancelJob(jobId: string): Promise<Job> {
  return fetchJson<Job>(`${API_BASE}/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export async function revertJob(jobId: string, toStep?: string): Promise<Job> {
  return fetchJson<Job>(`${API_BASE}/jobs/${jobId}/revert`, {
    method: "POST",
    body: JSON.stringify({ to_step: toStep }),
  });
}

// Artifacts API
export async function listJobArtifacts(jobId: string): Promise<Artifact[]> {
  return fetchJson<Artifact[]>(`${API_BASE}/jobs/${jobId}/artifacts`);
}

// Processors API
export async function listProcessors(): Promise<ProcessorInfo[]> {
  return fetchJson<ProcessorInfo[]>(`${API_BASE}/processors`);
}

export async function reloadProcessor(name: string): Promise<void> {
  await fetchJson(`${API_BASE}/processors/${name}/reload`, {
    method: "POST",
  });
}

// Stats API
export async function getStats(): Promise<PipelineStats> {
  return fetchJson<PipelineStats>(`${API_BASE}/stats`);
}

