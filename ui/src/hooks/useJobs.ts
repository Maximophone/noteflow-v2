import { useState, useEffect, useCallback } from "react";
import * as api from "../api/client";
import type { Job, PipelineStats } from "../types";

export function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      setLoading(true);
      const [jobsData, statsData] = await Promise.all([
        api.listJobs(),
        api.getStats(),
      ]);
      setJobs(jobsData);
      setStats(statsData);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshJobs();
  }, [refreshJobs]);

  return {
    jobs,
    stats,
    loading,
    error,
    refreshJobs,
  };
}

