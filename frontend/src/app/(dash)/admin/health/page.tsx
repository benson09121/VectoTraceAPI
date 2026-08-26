'use client';

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

export default function SystemHealthPage() {
  const fetchHealth = async () => {
    const data = await api.getSystemHealth();
    return data.metrics;
  };

  const { data: metrics, isLoading, error } = useQuery({
    queryKey: ['system-health'],
    queryFn: fetchHealth,
    refetchInterval: 10000,
  });

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">System Health</h1>
        <p className="text-muted-foreground mt-2">
          Real-time metrics for the VectoTrace monitoring engine and queue.
        </p>
      </div>

      {error && (
        <div className="bg-destructive/15 text-destructive p-4 rounded-md">
          {error.message || 'An error occurred'}
        </div>
      )}

      {isLoading && !metrics ? (
        <div className="animate-pulse flex space-x-4">
          <div className="h-32 bg-secondary rounded-md w-1/3"></div>
          <div className="h-32 bg-secondary rounded-md w-1/3"></div>
          <div className="h-32 bg-secondary rounded-md w-1/3"></div>
        </div>
      ) : metrics ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-card text-card-foreground border rounded-lg shadow-sm p-6">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">
              Active Workers
            </h3>
            <p className="text-4xl font-bold mt-2">
              {metrics.active_workers}
            </p>
            {metrics.active_workers_error && (
              <p className="text-xs text-destructive mt-2">{metrics.active_workers_error}</p>
            )}
          </div>

          <div className="bg-card text-card-foreground border rounded-lg shadow-sm p-6">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">
              Queue Depth
            </h3>
            <p className="text-4xl font-bold mt-2">
              {metrics.queue_depth > -1 ? metrics.queue_depth : 'Error'}
            </p>
            {metrics.queue_depth_error && (
              <p className="text-xs text-destructive mt-2">{metrics.queue_depth_error}</p>
            )}
          </div>

          <div className="bg-card text-card-foreground border rounded-lg shadow-sm p-6">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">
              Beat Heartbeat
            </h3>
            <p className="text-4xl font-bold mt-2 truncate">
              {metrics.beat_heartbeat}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
