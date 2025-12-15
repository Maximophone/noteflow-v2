import { useState } from "react";
import type { Job, StepResult } from "../types";
import * as api from "../api/client";

interface JobDetailProps {
  job: Job;
  onRefresh: () => void;
}

export function JobDetail({ job, onRefresh }: JobDetailProps) {
  const [loading, setLoading] = useState(false);

  const handleProcess = async () => {
    setLoading(true);
    try {
      await api.processJob(job.id);
      onRefresh();
    } catch (e) {
      console.error("Failed to process job:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!confirm("Are you sure you want to cancel this job?")) return;
    setLoading(true);
    try {
      await api.cancelJob(job.id);
      onRefresh();
    } catch (e) {
      console.error("Failed to cancel job:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleRevert = async () => {
    if (!confirm("Are you sure you want to revert all steps? This will undo all changes.")) return;
    setLoading(true);
    try {
      await api.revertJob(job.id);
      onRefresh();
    } catch (e) {
      console.error("Failed to revert job:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm("Are you sure you want to delete this job?")) return;
    setLoading(true);
    try {
      await api.deleteJob(job.id);
      onRefresh();
    } catch (e) {
      console.error("Failed to delete job:", e);
    } finally {
      setLoading(false);
    }
  };

  const formatDateTime = (isoString: string) => {
    return new Date(isoString).toLocaleString();
  };

  const getStepDotClass = (step: StepResult) => {
    switch (step.status) {
      case "completed":
        return "completed";
      case "running":
        return "running";
      case "failed":
        return "failed";
      case "awaiting_input":
        return "awaiting";
      default:
        return "";
    }
  };

  const allArtifacts = job.history.flatMap((step) => step.artifacts || []);

  return (
    <div className="job-detail">
      {/* Header */}
      <div className="job-detail-header">
        <h1 className="job-detail-title">{job.source_name}</h1>
        <div className="job-detail-meta">
          <span className={`job-status ${job.status}`}>{job.status}</span>
          <span>•</span>
          <span>{job.source_type}</span>
          <span>•</span>
          <span>Created {formatDateTime(job.created_at)}</span>
        </div>
        <div className="job-detail-actions">
          {job.status === "pending" && (
            <button className="btn btn-primary" onClick={handleProcess} disabled={loading}>
              ▶️ Process Now
            </button>
          )}
          {(job.status === "pending" || job.status === "processing") && (
            <button className="btn btn-secondary" onClick={handleCancel} disabled={loading}>
              Cancel
            </button>
          )}
          {job.history.length > 0 && (
            <button className="btn btn-secondary" onClick={handleRevert} disabled={loading}>
              ↩️ Revert All
            </button>
          )}
          <button className="btn btn-danger" onClick={handleDelete} disabled={loading}>
            🗑️ Delete
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {job.error_message && (
        <div className="section" style={{ borderColor: "var(--status-failed)" }}>
          <div className="section-header" style={{ background: "rgba(248, 81, 73, 0.1)" }}>
            <span className="section-title" style={{ color: "var(--status-failed)" }}>
              ⚠️ Error
            </span>
          </div>
          <div className="section-content">
            <pre style={{ fontFamily: "var(--font-mono)", fontSize: "12px", whiteSpace: "pre-wrap" }}>
              {job.error_message}
            </pre>
          </div>
        </div>
      )}

      {/* Processing Timeline */}
      <div className="section">
        <div className="section-header">
          <span className="section-title">📊 Processing Timeline</span>
        </div>
        <div className="section-content">
          {job.history.length === 0 ? (
            <div style={{ color: "var(--text-muted)", textAlign: "center", padding: "20px" }}>
              No processing steps yet
            </div>
          ) : (
            <div className="timeline">
              {job.history.map((step, index) => (
                <div key={step.id} className="timeline-item">
                  <div className={`timeline-dot ${getStepDotClass(step)}`} />
                  <div className="timeline-content">
                    <div className="timeline-header">
                      <span className="timeline-title">{step.step_name}</span>
                      {step.completed_at && (
                        <span className="timeline-time">
                          {formatDateTime(step.completed_at)}
                        </span>
                      )}
                    </div>
                    <div className="timeline-description">
                      <span className={`job-status ${step.status}`}>{step.status}</span>
                      {step.error_message && (
                        <span style={{ marginLeft: "8px", color: "var(--status-failed)" }}>
                          {step.error_message}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Artifacts */}
      <div className="section">
        <div className="section-header">
          <span className="section-title">📁 Artifacts ({allArtifacts.length})</span>
        </div>
        <div className="section-content">
          {allArtifacts.length === 0 ? (
            <div style={{ color: "var(--text-muted)", textAlign: "center", padding: "20px" }}>
              No artifacts created yet
            </div>
          ) : (
            <div className="artifact-list">
              {allArtifacts.map((artifact) => (
                <div key={artifact.id} className="artifact-item">
                  <div className="artifact-info">
                    <div className="artifact-icon">
                      {artifact.artifact_type.includes("file") ? "📄" : "🔗"}
                    </div>
                    <div>
                      <div className="artifact-path">{artifact.target}</div>
                      <div className="artifact-type">{artifact.artifact_type}</div>
                    </div>
                  </div>
                  <span className={`artifact-status ${artifact.status}`}>
                    {artifact.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Job Data */}
      {Object.keys(job.data).length > 0 && (
        <div className="section">
          <div className="section-header">
            <span className="section-title">📋 Job Data</span>
          </div>
          <div className="section-content">
            <pre style={{ fontFamily: "var(--font-mono)", fontSize: "12px", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(job.data, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

