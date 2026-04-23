export interface Device {
  id: string;
  name: string;
  location: string | null;
  type: string | null;
  status: 'online' | 'offline' | 'warning' | 'fault';
  last_seen: string | null;
  created_at: string;
}

export interface Telemetry {
  id: string;
  device_id: string;
  temperature: number | null;
  humidity: number | null;
  vibration_x: number | null;
  vibration_y: number | null;
  vibration_z: number | null;
  light_level: number | null;
  anomaly_score: number | null;
  is_anomaly: boolean;
  recorded_at: string;
}

export interface Alert {
  id: string;
  device_id: string;
  rule_id: string | null;
  message: string | null;
  severity: 'info' | 'warning' | 'critical';
  resolved: boolean;
  triggered_at: string;
  resolved_at: string | null;
}

export interface Ticket {
  id: string;
  device_id: string | null;
  alert_id: string | null;
  title: string | null;
  description: string | null;
  status: 'open' | 'in_progress' | 'closed';
  priority: 'low' | 'medium' | 'high' | 'critical' | null;
  assigned_to: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface User {
  id: string;
  name: string | null;
  email: string;
  role: 'admin' | 'technician' | 'viewer';
}
