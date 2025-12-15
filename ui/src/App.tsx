import { useState, useEffect } from "react";
import { Sidebar } from "./components/Sidebar";
import { JobDetail } from "./components/JobDetail";
import { Header } from "./components/Header";
import { useWebSocket } from "./hooks/useWebSocket";
import { useJobs } from "./hooks/useJobs";
import type { Job } from "./types";

function App() {
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const { jobs, refreshJobs, stats } = useJobs();
  const { lastMessage, isConnected } = useWebSocket("ws://localhost:8000/ws");

  // Refresh jobs when we receive a WebSocket message
  useEffect(() => {
    if (lastMessage) {
      refreshJobs();
    }
  }, [lastMessage, refreshJobs]);

  const selectedJob = jobs.find((j) => j.id === selectedJobId) || null;

  return (
    <div className="app">
      <Header stats={stats} isConnected={isConnected} />
      <div className="main-content">
        <Sidebar
          jobs={jobs}
          selectedJobId={selectedJobId}
          onSelectJob={setSelectedJobId}
          onRefresh={refreshJobs}
        />
        <main className="content-area">
          {selectedJob ? (
            <JobDetail job={selectedJob} onRefresh={refreshJobs} />
          ) : (
            <div className="empty-state">
              <div className="empty-icon">📋</div>
              <h2>No Job Selected</h2>
              <p>Select a job from the sidebar to view details</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;

