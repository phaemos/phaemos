export interface Device {
  id: string;
  name: string;
  location: string | null;
  type: string | null;
  status: 'online' | 'offline' | 'warning' | 'fault';
  last_seen: string | null;
  firmware_version: string | null;
  created_at: string;
}

export interface Telemetry {
  id: string;
  device_id: string;
  // node_type identifies which physical board sent this reading
  node_type: string | null;

  // BME280
  temperature: number | null;
  humidity: number | null;
  pressure: number | null;

  // MPU6050 accelerometer (g-units) and gyroscope (degrees/second)
  vibration_x: number | null;
  vibration_y: number | null;
  vibration_z: number | null;
  gyro_x: number | null;
  gyro_y: number | null;
  gyro_z: number | null;

  // INA219 current monitor
  bus_voltage: number | null;
  current_ma: number | null;
  power_mw: number | null;

  // MLX90614 IR surface temperature
  ir_temperature: number | null;

  // VL53L0X time-of-flight distance
  distance_mm: number | null;

  // MQ-2 gas sensor
  gas_level: number | null;
  gas_alert: boolean | null;

  // AS5600 magnetic encoder
  shaft_angle: number | null;
  shaft_rpm: number | null;

  // MAX4466 microphone level
  sound_level: number | null;

  // LDR ambient light
  light_level: number | null;

  // DS18B20 contact temperature
  contact_temp: number | null;

  // FC-28 water ingress
  moisture_level: number | null;
  water_detected: boolean | null;

  // STM32 Black Pill FFT output forwarded via ESP32 UART parser
  fft_peak_hz: number | null;
  vib_magnitude: number | null;

  // ML anomaly detection output
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

export interface AlertRule {
  id: string;
  device_id: string;
  metric: string;
  condition: 'gt' | 'lt' | 'eq';
  threshold: number;
  severity: 'info' | 'warning' | 'critical';
  created_at: string;
}

export interface User {
  id: string;
  name: string | null;
  email: string;
  role: 'admin' | 'technician' | 'viewer';
  created_at?: string;
}
