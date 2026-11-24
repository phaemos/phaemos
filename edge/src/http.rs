//! the one place the HTTP client crate is used.
//!
//! ureq 3 with its default features verifies the server's certificate with rustls against the
//! Mozilla root list built into the binary (webpki-roots). It does not read the operating
//! system's trust store. There is no switch here that turns checking off. Redirects are
//! refused so the key is never sent to another address. No proxy is used: ureq would otherwise read
//! `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` from the environment. A gateway started under a
//! service manager or a shell profile could then send the key and the readings through a host nobody
//! chose for it. A site that needs a proxy should say so in a flag added for the purpose.

use std::time::Duration;

use phaemos_edge::forward::{BatchReply, ItemResult, Reply, Sender};

/// the longest one request may take from start to finish.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);

pub struct UreqSender {
    agent: ureq::Agent,
    url: String,
    batch_url: String,
    key: String,
    /// set once the server answered the batch route with 404 or 405: it is not asked again this run.
    no_batch: bool,
}

impl UreqSender {
    pub fn new(api_url: &str, key: String) -> Self {
        let config = ureq::Agent::config_builder()
            .timeout_global(Some(REQUEST_TIMEOUT))
            .http_status_as_error(false)
            .max_redirects(0)
            .proxy(None)
            .build();
        Self {
            agent: ureq::Agent::new_with_config(config),
            url: format!("{api_url}/api/v1/telemetry"),
            batch_url: format!("{api_url}/api/v1/telemetry/batch"),
            key,
            no_batch: false,
        }
    }
}

/// reads the answer of the batch route:
/// {"results": [{"index", "status", "outcome", "id", "code", "detail", "backlog"}], "stored", "duplicate", "refused"}
/// with one result for each reading in the order sent. `status` is what a single post of that reading would
/// have answered (201 stored, 200 duplicate, 409 or 422 refused).
fn batch_items(body: &str) -> Vec<ItemResult> {
    let Ok(value) = serde_json::from_str::<serde_json::Value>(body) else {
        return Vec::new();
    };
    value
        .get("results")
        .and_then(serde_json::Value::as_array)
        .map(|list| {
            list.iter()
                .map(|item| ItemResult {
                    status: item
                        .get("status")
                        .and_then(serde_json::Value::as_u64)
                        .and_then(|s| u16::try_from(s).ok())
                        .unwrap_or(0),
                    code: item
                        .get("code")
                        .and_then(serde_json::Value::as_str)
                        .map(str::to_string),
                    backlog: item
                        .get("backlog")
                        .and_then(serde_json::Value::as_bool)
                        .unwrap_or(false),
                })
                .collect()
        })
        .unwrap_or_default()
}

/// the batch route allows 1,200 readings a minute for one device, which is one reading every 50 ms. This is the
/// wait after a batch of `readings` that took `elapsed`, so a long drain stays inside the allowance and is not
/// answered 429 (and so refused whole) over and over. It is capped, so one batch never holds the loop long.
fn pace(readings: usize, elapsed: Duration) -> Duration {
    let allowed = Duration::from_millis(50) * u32::try_from(readings).unwrap_or(u32::MAX);
    allowed.min(Duration::from_secs(6)).saturating_sub(elapsed)
}

impl Sender for UreqSender {
    fn send_batch(&mut self, bodies: &[String]) -> Result<Option<BatchReply>, String> {
        if self.no_batch {
            return Ok(None);
        }
        // the readings are already JSON objects, so the body is built by joining them
        let began = std::time::Instant::now();
        let body = format!("{{\"readings\":[{}]}}", bodies.join(","));
        let result = self
            .agent
            .post(&self.batch_url)
            .header("X-API-Key", &self.key)
            .header("Content-Type", "application/json")
            .send(body.as_str());
        match result {
            Ok(mut response) => {
                let status = response.status().as_u16();
                if status == 404 || status == 405 {
                    self.no_batch = true;
                    return Ok(None);
                }
                let retry_after = response
                    .headers()
                    .get("retry-after")
                    .and_then(|v| v.to_str().ok())
                    .map(str::to_string);
                let text = if (200..300).contains(&status) {
                    response.body_mut().read_to_string().unwrap_or_default()
                } else {
                    String::new()
                };
                let items = batch_items(&text);
                // stay inside the device's allowance on the next batch
                if (200..300).contains(&status) {
                    std::thread::sleep(pace(bodies.len(), began.elapsed()));
                }
                Ok(Some(BatchReply {
                    status,
                    retry_after,
                    items,
                }))
            }
            Err(error) => Err(error.to_string().replace(&self.key, "<key>")),
        }
    }

    fn send(&mut self, body: &str) -> Result<Reply, String> {
        let result = self
            .agent
            .post(&self.url)
            .header("X-API-Key", &self.key)
            .header("Content-Type", "application/json")
            .send(body);
        match result {
            Ok(response) => Ok(Reply {
                status: response.status().as_u16(),
                retry_after: response
                    .headers()
                    .get("retry-after")
                    .and_then(|v| v.to_str().ok())
                    .map(str::to_string),
            }),
            // an error text never holds a header, but the key is scrubbed all the same
            Err(error) => Err(error.to_string().replace(&self.key, "<key>")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::UreqSender;
    use phaemos_edge::forward::Sender;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{mpsc, Mutex};
    use std::thread;

    /// the proxy test changes the environment, so the tests here run one at a time.
    static ENV: Mutex<()> = Mutex::new(());

    /// a one-shot server on 127.0.0.1 that answers with `reply` and sends the request text back.
    fn serve(reply: &'static str) -> (String, mpsc::Receiver<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { break };
                let mut request = Vec::new();
                let mut chunk = [0u8; 4096];
                loop {
                    let n = stream.read(&mut chunk).unwrap_or(0);
                    request.extend_from_slice(&chunk[..n]);
                    let text = String::from_utf8_lossy(&request);
                    if n == 0 {
                        break;
                    }
                    if let Some(split) = text.find("\r\n\r\n") {
                        let length = text
                            .lines()
                            .find_map(|l| {
                                l.to_ascii_lowercase()
                                    .strip_prefix("content-length:")
                                    .map(|v| v.trim().parse::<usize>().unwrap_or(0))
                            })
                            .unwrap_or(0);
                        if request.len() >= split + 4 + length {
                            break;
                        }
                    }
                }
                let _ = tx.send(String::from_utf8_lossy(&request).into_owned());
                let _ = stream.write_all(reply.as_bytes());
            }
        });
        (url, rx)
    }

    #[test]
    fn sends_the_key_header_and_body_and_reads_status_and_retry_after() {
        let _guard = ENV
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let (url, seen) =
            serve("HTTP/1.1 429 Too Many Requests\r\nRetry-After: 45\r\nContent-Length: 0\r\n\r\n");
        let mut sender = UreqSender::new(&url, "test-key-123".to_string());
        let reply = sender.send(r#"{"device_id":"d1"}"#).unwrap();
        assert_eq!(reply.status, 429);
        assert_eq!(reply.retry_after.as_deref(), Some("45"));
        let request = seen.recv().unwrap();
        assert!(request.starts_with("POST /api/v1/telemetry "));
        assert!(request
            .to_ascii_lowercase()
            .contains("x-api-key: test-key-123"));
        assert!(request
            .to_ascii_lowercase()
            .contains("content-type: application/json"));
        assert!(request.ends_with(r#"{"device_id":"d1"}"#));
    }

    #[test]
    fn a_4xx_is_a_reply_not_an_error() {
        let _guard = ENV
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let (url, _) = serve("HTTP/1.1 422 Unprocessable Entity\r\nContent-Length: 0\r\n\r\n");
        let reply = UreqSender::new(&url, "k".to_string()).send("{}").unwrap();
        assert_eq!(reply.status, 422);
    }

    #[test]
    fn a_redirect_is_returned_and_not_followed() {
        let _guard = ENV
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let (target, elsewhere) = serve("HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n");
        let reply_text: &'static str = Box::leak(
            format!("HTTP/1.1 307 Temporary Redirect\r\nLocation: {target}/x\r\nContent-Length: 0\r\n\r\n").into_boxed_str(),
        );
        let (url, _) = serve(reply_text);
        let reply = UreqSender::new(&url, "k".to_string()).send("{}").unwrap();
        assert_eq!(reply.status, 307);
        assert!(
            elsewhere
                .recv_timeout(std::time::Duration::from_millis(300))
                .is_err(),
            "the redirect target was contacted"
        );
    }

    #[test]
    fn a_dead_port_is_an_error_without_the_key() {
        let _guard = ENV
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let port = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let mut sender = UreqSender::new(
            &format!("http://127.0.0.1:{port}"),
            "secret-key-xyz".to_string(),
        );
        let error = sender.send("{}").unwrap_err();
        assert_ne!(error, "");
        assert!(!error.contains("secret-key-xyz"));
    }

    #[test]
    fn the_proxy_environment_is_ignored() {
        let _guard = ENV
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        // a proxy that would catch the request if it were used. The variable is set for this process
        // only. The request must still go straight to the server.
        let (proxy, caught) = serve("HTTP/1.1 500 Proxy Was Used\r\nContent-Length: 0\r\n\r\n");
        let (url, _) = serve("HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n");
        std::env::set_var("HTTP_PROXY", &proxy);
        std::env::set_var("http_proxy", &proxy);
        std::env::set_var("ALL_PROXY", &proxy);
        let reply = UreqSender::new(&url, "k".to_string()).send("{}").unwrap();
        std::env::remove_var("HTTP_PROXY");
        std::env::remove_var("http_proxy");
        std::env::remove_var("ALL_PROXY");
        assert_eq!(reply.status, 201);
        assert!(caught
            .recv_timeout(std::time::Duration::from_millis(200))
            .is_err());
    }

    #[test]
    fn a_batch_is_one_post_with_a_result_for_each_reading() {
        let _guard = ENV
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let (url, seen) = serve("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 58\r\n\r\n{\"results\":[{\"status\":201},{\"status\":409},{\"status\":422}]}");
        let mut sender = UreqSender::new(&url, "batch-key".to_string());
        let lines = vec![
            r#"{"device_id":"a"}"#.to_string(),
            r#"{"device_id":"b"}"#.to_string(),
            r#"{"device_id":"c"}"#.to_string(),
        ];
        let reply = sender.send_batch(&lines).unwrap().unwrap();
        let statuses: Vec<u16> = reply.items.iter().map(|i| i.status).collect();
        assert_eq!((reply.status, statuses), (200, vec![201, 409, 422]));
        let request = seen.recv().unwrap();
        assert!(request.starts_with("POST /api/v1/telemetry/batch "));
        assert!(request
            .to_ascii_lowercase()
            .contains("x-api-key: batch-key"));
        assert!(request
            .ends_with(r#"{"readings":[{"device_id":"a"},{"device_id":"b"},{"device_id":"c"}]}"#));
    }

    #[test]
    fn a_404_means_no_batch_route_and_it_is_not_asked_again() {
        let _guard = ENV
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let (url, seen) = serve("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n");
        let mut sender = UreqSender::new(&url, "k".to_string());
        let lines = vec![r#"{"device_id":"a"}"#.to_string()];
        assert!(sender.send_batch(&lines).unwrap().is_none());
        assert!(seen.recv().is_ok());
        assert!(sender.send_batch(&lines).unwrap().is_none());
        assert!(
            seen.recv_timeout(std::time::Duration::from_millis(200))
                .is_err(),
            "the batch route was asked again"
        );
    }

    #[test]
    fn a_batch_429_keeps_its_retry_after() {
        let _guard = ENV
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let (url, _) =
            serve("HTTP/1.1 429 Too Many Requests\r\nRetry-After: 12\r\nContent-Length: 0\r\n\r\n");
        let mut sender = UreqSender::new(&url, "k".to_string());
        let reply = sender.send_batch(&["{}".to_string()]).unwrap().unwrap();
        assert_eq!(
            (reply.status, reply.retry_after.as_deref()),
            (429, Some("12"))
        );
    }

    #[test]
    fn batch_items_reads_the_documented_answer() {
        let body = r#"{"results":[
            {"index":0,"status":201,"outcome":"stored","id":"u","backlog":true},
            {"index":1,"status":200,"outcome":"duplicate","detail":"d"},
            {"index":2,"status":409,"outcome":"refused","code":"replay_stale","detail":"x"},
            {"index":3,"status":422,"outcome":"refused","code":"observed_at_too_old","detail":"y"}],
            "stored":1,"duplicate":1,"refused":2}"#;
        let items = super::batch_items(body);
        assert_eq!(items.len(), 4);
        assert_eq!(
            (items[0].status, items[0].backlog, items[0].code.clone()),
            (201, true, None)
        );
        assert_eq!((items[1].status, items[1].backlog), (200, false));
        assert_eq!(
            (items[2].status, items[2].code.as_deref()),
            (409, Some("replay_stale"))
        );
        assert_eq!(
            (items[3].status, items[3].code.as_deref()),
            (422, Some("observed_at_too_old"))
        );
    }

    #[test]
    fn batch_items_reads_what_it_can_and_nothing_else() {
        assert_eq!(super::batch_items("not json").len(), 0);
        assert_eq!(super::batch_items(r#"{"other":1}"#).len(), 0);
        assert_eq!(
            super::batch_items(r#"{"results":[{"nope":1}]}"#)[0].status,
            0
        );
    }

    #[test]
    fn the_drain_is_paced_to_the_devices_allowance() {
        use super::pace;
        use std::time::Duration;
        // 1,200 readings a minute is one every 50 ms
        assert_eq!(pace(100, Duration::ZERO), Duration::from_secs(5));
        assert_eq!(pace(100, Duration::from_secs(2)), Duration::from_secs(3));
        assert_eq!(pace(100, Duration::from_secs(9)), Duration::ZERO);
        assert_eq!(pace(1, Duration::ZERO), Duration::from_millis(50));
        assert_eq!(pace(10_000, Duration::ZERO), Duration::from_secs(6));
    }
}
