import type { AlertEvidence, DeviceModel, ReplayFields } from './monitoring';
export type { MlStatus, MlRetrain, MlRetrainModel, DeviceModel, AlertEvidence, ReplayFields } from './monitoring';

export interface DeviceHealth {
  boot_count?: number | null;
  uptime_s?: number | null;
  reset_reason?: string | null;
  rssi?: number | null;
  heap_free?: number | null;
  firmware_version?: string | null;
  last_seq?: number | null;
  reported_at?: string | null;
  // sensor key to state, for each sensor that cannot be trusted. Empty or absent when all is well
  faults?: Record<string, string> | null;
  // what the server found for itself in the latest post: stuck for a value that stopped moving and out_of_range for one beyond
  // what the part can measure. They raise the same sensor alerts as a fault the node reports.
  server_faults?: Record<string, string> | null;
  lost_posts?: number | null;
  last_gap_at?: string | null;
  reset_loop?: boolean | null;
  dropped_fields?: number | null;
  // the latest serial link counters the hub sent, by link name (nano, stm32)
  links?: Record<string, { ok?: number; crc?: number; gaps?: number; restarts?: number; st?: number; up?: number; vcc?: number }> | null;
  // alert rules that cannot fire now because the sensor behind their field is faulted or not fitted
  rules_cannot_evaluate?: RuleCannotEvaluate[] | null;
  // sensors the firmware build does not carry and bench diagnostics the node sent. Their shapes are read as they come.
  not_fitted_by_firmware?: string[] | null;
  diag?: Record<string, unknown> | null;
  // true while the firmware image was built for another board
  board_mismatch?: boolean | null;
}

export interface RuleCannotEvaluate {
  rule_id: string;
  metric: string;
  sensor_key: string | null;
  state: string;
  reason: string;
}

export interface Device extends ReplayFields {
  id: string;
  name: string;
  location: string | null;
  type: string | null;
  status: 'online' | 'offline' | 'warning' | 'fault';
  // how recently the node posted. Absent from an older API, which lib/machineState.ts then works out from last_seen.
  link_state?: 'online' | 'late' | 'offline';
  expected_interval_s?: number;
  seconds_since_last_post?: number | null;
  // the latest vitals and faults the node reported. Null for a node that has never sent a health field. Filled by the
  // machine's own route and by the list.
  health?: DeviceHealth | null;
  // sensor keys an admin marked as not fitted on this machine. Absent from an older API.
  not_fitted?: string[] | null;
  not_fitted_by_firmware?: string[] | null;
  last_seen: string | null;
  firmware_version: string | null;
  tags: string[] | null;
  owner_id: string | null;
  // the owner's name or null for a machine nobody owns
  owner_name?: string | null;
  // the anomaly model's state for this machine. Absent from an older API.
  model?: DeviceModel | null;
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
  // the vibration node's strength figures, in g: the root mean square of each axis, the largest sample and the axis means
  vib_rms_x?: number | null;
  vib_rms_y?: number | null;
  vib_rms_z?: number | null;
  vib_peak?: number | null;
  // true while a sample in the window reached the vibration sensor's limit. A reading, not a fault: the values stay.
  vib_clipping?: boolean | null;
  stm32_vib_x?: number | null;
  stm32_vib_y?: number | null;
  stm32_vib_z?: number | null;
  // the Nano node's own readings. Light and moisture are raw counts (0 to 1023).
  nano_temp?: number | null;
  nano_hum?: number | null;
  nano_pres?: number | null;
  nano_light?: number | null;
  nano_moist?: number | null;
  nano_water?: boolean | null;

  // ML anomaly detection output
  anomaly_score: number | null;
  is_anomaly: boolean;
  recorded_at: string;
  // what the node reported about the sensors on this row. Null when it sent no fault.
  quality?: { faults?: Record<string, string> | null; not_applied?: string[] | null; backlog?: boolean | null; received_at?: string | null; observed_at_ignored?: string | null; rejected?: Record<string, unknown> | null; scored_by?: string | null; dropped_values?: string[] | null; scoring_error?: string | null } | null;
}

// one row of GET /telemetry/{id}?bucket=SECONDS. Same sensor fields as Telemetry, but each is the mean of the bucket's
// rows, except shaft_angle (circular mean), anomaly_score and vib_magnitude (maximum), fft_peak_hz (taken from the
// strongest vibration) and the flags (true when any reading raised them). recorded_at is the start of the bucket;
// there is no id or node_type.
export interface TelemetryBucket extends Omit<Telemetry, 'id' | 'node_type'> {
  // rows (posts) in the bucket, not readings of any one column
  reading_count: number;
  // largest absolute value of each signed axis in the bucket. The field of the same name without the suffix is its mean
  vibration_x_peak: number | null;
  vibration_y_peak: number | null;
  vibration_z_peak: number | null;
  gyro_x_peak: number | null;
  gyro_y_peak: number | null;
  gyro_z_peak: number | null;
}

export interface Alert {
  id: string;
  device_id: string;
  rule_id: string | null;
  message: string | null;
  severity: 'info' | 'warning' | 'critical';
  // 'machine' for an alert about the machine, 'monitoring' for one about how it is watched. Absent from an older API.
  category?: 'machine' | 'monitoring';
  // the sensor a monitoring alert is about or null
  sensor_key?: string | null;
  // offline, reset_loop, unscored, sensor or clipping for an alert the system raised and null for a rule or model alert
  kind?: 'rule' | 'anomaly' | 'offline' | 'reset_loop' | 'unscored' | 'sensor' | 'clipping' | 'board_mismatch' | null;
  resolved: boolean;
  // when the alert was raised, which is one hold after the condition first held
  triggered_at: string;
  resolved_at: string | null;
  // an alert lasts as long as its condition: one row per machine and rule, updated in place. Absent from an older API, where each
  // reading made a row of its own.
  occurrences?: number;
  last_value?: number | null;
  // the most extreme value (the highest for over, the lowest for under). For the model's alert, the highest score.
  peak_value?: number | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  // true while a reading met the condition in the last two minutes. Null for an alert the system raised.
  still_occurring?: boolean | null;
  // the figures behind a model alert. Null on every other alert.
  evidence?: AlertEvidence | null;
}

export interface Ticket {
  id: string;
  ticket_number: number | null;
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
  // from GET /auth/users, which now carries these. See lib/people.ts.
  oauth_provider?: string | null;
  totp_enabled?: boolean;
  is_active?: boolean;
  last_login?: string | null;
  session_count?: number;
  is_service?: boolean;
}
