// Types for NoteFlow v2 UI

export type JobStatus =
  | "pending"
  | "processing"
  | "awaiting_input"
  | "completed"
  | "failed"
  | "cancelled"
  | "reverting"
  | "reverted";

export type ArtifactStatus =
  | "pending"
  | "created"
  | "reverted"
  | "failed"
  | "orphaned"
  | "irreversible";

export type ArtifactType =
  | "file_create"
  | "file_modify"
  | "file_delete"
  | "file_move"
  | "frontmatter_update"
  | "external_api_create"
  | "external_api_modify"
  | "metadata";

export interface Artifact {
  id: string;
  job_id: string;
  step_name: string;
  artifact_type: ArtifactType;
  target: string;
  before_state?: string;
  after_state?: string;
  metadata: Record<string, unknown>;
  status: ArtifactStatus;
  reversibility: string;
  error_message?: string;
  created_at: string;
  reverted_at?: string;
}

export interface StepResult {
  id: string;
  job_id: string;
  step_name: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  output_data: Record<string, unknown>;
  error_message?: string;
  error_traceback?: string;
  awaiting_input_since?: string;
  user_input?: Record<string, unknown>;
  reverted_at?: string;
  revert_error?: string;
  artifacts: Artifact[];
}

export interface Job {
  id: string;
  source_type: string;
  source_name: string;
  source_path?: string;
  source_url?: string;
  status: JobStatus;
  current_step?: string;
  data: Record<string, unknown>;
  history: StepResult[];
  tags: string[];
  priority: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface PipelineStats {
  running: boolean;
  active_jobs: number;
  max_concurrent: number;
  processors_loaded: number;
  jobs_by_status: Record<string, number>;
}

export interface ProcessorInfo {
  name: string;
  display_name: string;
  description: string;
  version: string;
  requires: string[];
  has_ui: boolean;
  requires_input: string;
}

export interface WebSocketMessage {
  event: string;
  job_id?: string;
  step_name?: string;
  status?: string;
  error?: string;
  job?: Job;
}

