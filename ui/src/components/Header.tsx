import type { PipelineStats } from "../types";

interface HeaderProps {
  stats: PipelineStats | null;
  isConnected: boolean;
}

export function Header({ stats, isConnected }: HeaderProps) {
  return (
    <header className="header">
      <div className="header-left">
        <h1 className="header-title">NoteFlow</h1>
        {stats && (
          <div className="header-stats">
            <div className="header-stat">
              <span>Processors:</span>
              <span className="header-stat-value">{stats.processors_loaded}</span>
            </div>
            <div className="header-stat">
              <span>Active:</span>
              <span className="header-stat-value">
                {stats.active_jobs}/{stats.max_concurrent}
              </span>
            </div>
          </div>
        )}
      </div>
      <div className="connection-status">
        <span className={`connection-dot ${isConnected ? "connected" : ""}`} />
        <span>{isConnected ? "Connected" : "Disconnected"}</span>
      </div>
    </header>
  );
}

