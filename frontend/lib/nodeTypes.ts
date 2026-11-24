// the node types the backend knows (schemas/telemetry.py) with the plain names the interface uses. The machine
// "type" column is free text up to 50 characters, so an unknown value is shown as it was stored.

export const NODE_TYPES = [
  { value: 'esp32', label: 'ESP32 hub' },
  { value: 'stm32', label: 'STM32 vibration node' },
  { value: 'nano', label: 'Arduino Nano node' },
  { value: 'pico_w', label: 'Pico 2 W ambient node' },
] as const;

export function nodeTypeLabel(type: string | null | undefined): string {
  if (!type) return 'Not set';
  return NODE_TYPES.find((n) => n.value === type)?.label ?? type;
}
