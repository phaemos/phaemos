import DataTable from '@/components/ui/DataTable';

// the sensor list from docs/sensor_reference.md. Where that file and the firmware disagree the firmware wins:
// acceleration is sent in g (esp32.ino) and the gas level is a 0 to 1023 scale (sensors/mq2.cpp), not ppm.
const SENSORS: { sensor: string; measures: string; nodes: string; unit: string }[] = [
  { sensor: 'BME280', measures: 'Air temperature, humidity and pressure', nodes: 'ESP32 hub, Arduino Nano, Pico 2W', unit: 'degC, %, hPa' },
  { sensor: 'DS18B20', measures: 'Temperature by contact probe', nodes: 'ESP32 hub', unit: 'degC' },
  { sensor: 'MLX90614', measures: 'Surface temperature without contact', nodes: 'ESP32 hub', unit: 'degC' },
  { sensor: 'MPU6050', measures: 'Acceleration and rotation rate on three axes', nodes: 'ESP32 hub, STM32 Black Pill', unit: 'g, deg/s' },
  { sensor: 'MPU6050 with FFT', measures: 'Vibration magnitude and dominant vibration frequency', nodes: 'STM32 Black Pill', unit: 'g, Hz' },
  { sensor: 'INA219', measures: 'Bus voltage, current and power', nodes: 'ESP32 hub', unit: 'V, mA, mW' },
  { sensor: 'MQ-2', measures: 'Gas and smoke level, with an alarm flag', nodes: 'ESP32 hub', unit: '0 to 1023 scale' },
  { sensor: 'MAX4466', measures: 'Sound level', nodes: 'ESP32 hub', unit: 'ADC counts' },
  { sensor: 'VL53L0X', measures: 'Distance to an object', nodes: 'ESP32 hub', unit: 'mm' },
  { sensor: 'AS5600', measures: 'Shaft angle and shaft speed', nodes: 'ESP32 hub', unit: 'degrees, RPM' },
  { sensor: 'LDR', measures: 'Ambient light', nodes: 'ESP32 hub, Arduino Nano, Pico 2W', unit: 'ADC counts' },
  { sensor: 'FC-28', measures: 'Soil or water moisture, with a water flag', nodes: 'ESP32 hub, Arduino Nano', unit: 'ADC counts' },
];

// the table scrolls inside its own focusable region at narrow widths: restacking four columns into cards would
// make a reader lose the row-by-row comparison the table exists for. DataTable makes the wrapper a labelled,
// focusable region when it is given a max-height class so max-h-none costs nothing.
export default function SensorTable() {
  return (
    <DataTable caption="Sensors, what each measures, the node that carries it and the unit" maxHeightClass="max-h-none" framed minWidth="44rem">
      <thead>
        <tr>
          <th scope="col">Sensor</th>
          <th scope="col">Measures</th>
          <th scope="col">Node</th>
          <th scope="col">Unit</th>
        </tr>
      </thead>
      <tbody>
        {SENSORS.map((s) => (
          <tr key={s.sensor}>
            <th scope="row" className="font-mono">{s.sensor}</th>
            <td>{s.measures}</td>
            <td>{s.nodes}</td>
            <td className="font-mono">{s.unit}</td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}
