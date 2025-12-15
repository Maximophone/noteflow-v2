import type { Job } from "../types";
import * as api from "../api/client";

interface SidebarProps {
  jobs: Job[];
  selectedJobId: string | null;
  onSelectJob: (id: string) => void;
  onRefresh: () => void;
}

export function Sidebar({ jobs, selectedJobId, onSelectJob, onRefresh }: SidebarProps) {
  const formatTime = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return "just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  const handleCreateTestJob = async () => {
    try {
      const job = await api.createJob({
        source_type: "example",
        source_name: `Test Job ${new Date().toLocaleTimeString()}`,
        data: { run_example: true },
        tags: ["test"],
      });
      onRefresh();
      onSelectJob(job.id);
    } catch (e) {
      console.error("Failed to create job:", e);
      alert("Failed to create job. Is the server running?");
    }
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-title">Jobs</span>
        <div className="sidebar-actions">
          <button className="icon-button" onClick={handleCreateTestJob} title="Create Test Job">
            ➕
          </button>
          <button className="icon-button" onClick={onRefresh} title="Refresh">
            🔄
          </button>
        </div>
      </div>
      <div className="job-list">
        {jobs.length === 0 ? (
          <div className="empty-state" style={{ padding: "40px 20px" }}>
            <div className="empty-icon" style={{ fontSize: "32px" }}>📭</div>
            <p style={{ marginTop: "8px" }}>No jobs yet</p>
          </div>
        ) : (
          jobs.map((job) => (
            <div
              key={job.id}
              className={`job-item ${job.id === selectedJobId ? "selected" : ""}`}
              onClick={() => onSelectJob(job.id)}
            >
              <div className="job-item-header">
                <span className="job-item-name">{job.source_name}</span>
                <span className={`job-status ${job.status}`}>{job.status}</span>
              </div>
              <div className="job-item-meta">
                <span>{job.source_type}</span>
                <span>•</span>
                <span>{formatTime(job.created_at)}</span>
                {job.current_step && (
                  <>
                    <span>•</span>
                    <span>{job.current_step}</span>
                  </>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}

