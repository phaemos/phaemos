//! Validation of readings arriving from the sensor nodes.

use serde_json::Value;

/// Parses one line from a node. A reading must be a JSON object with a non-empty
/// string `device_id`, matching what the API's telemetry ingest expects.
///
/// # Errors
///
/// Returns a description of the problem when the line is not a valid reading.
pub fn parse_line(line: &str) -> Result<Value, String> {
    let value: Value = serde_json::from_str(line.trim()).map_err(|e| format!("not JSON: {e}"))?;
    let object = value.as_object().ok_or("reading must be a JSON object")?;
    match object.get("device_id").and_then(Value::as_str) {
        Some(id) if !id.is_empty() => Ok(value),
        _ => Err("reading needs a non-empty string device_id".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::parse_line;

    #[test]
    fn accepts_a_reading() {
        let value = parse_line(r#"{"device_id":"node-1","temperature":24.1}"#).unwrap();
        assert_eq!(value["temperature"], 24.1);
    }

    #[test]
    fn rejects_bad_lines() {
        assert!(parse_line("not json").is_err());
        assert!(parse_line("[1,2,3]").is_err());
        assert!(parse_line(r#"{"temperature":24.1}"#).is_err());
        assert!(parse_line(r#"{"device_id":""}"#).is_err());
    }
}
