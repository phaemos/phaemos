//! reads input lines with a length cap, so one endless line cannot use up the memory.

use std::io::{self, BufRead};

#[derive(Debug, PartialEq, Eq)]
pub enum Line {
    Text(String),
    /// the line was longer than the cap. It was read and thrown away up to its end.
    TooLong(usize),
    Eof,
}

/// reads one line of at most `max` bytes (not counting the newline).
///
/// # Errors
///
/// returns any error from the reader.
pub fn read_line<R: BufRead>(reader: &mut R, max: usize) -> io::Result<Line> {
    let mut line: Vec<u8> = Vec::new();
    let mut total = 0usize;
    let mut seen_any = false;
    loop {
        let (used, found_end) = {
            let chunk = reader.fill_buf()?;
            if chunk.is_empty() {
                break;
            }
            seen_any = true;
            let end = chunk.iter().position(|&b| b == b'\n');
            let part = end.unwrap_or(chunk.len());
            // keep bytes only while the line still fits: past the cap they are only counted
            if total < max {
                let room = max - total;
                line.extend_from_slice(&chunk[..part.min(room)]);
            }
            total += part;
            (end.map_or(chunk.len(), |i| i + 1), end.is_some())
        };
        reader.consume(used);
        if found_end {
            return Ok(finish(&line, total, max));
        }
    }
    if !seen_any {
        return Ok(Line::Eof);
    }
    Ok(finish(&line, total, max))
}

fn finish(line: &[u8], total: usize, max: usize) -> Line {
    if total > max {
        Line::TooLong(total)
    } else {
        // a stray carriage return from a serial bridge is not part of the reading
        Line::Text(
            String::from_utf8_lossy(line)
                .trim_end_matches('\r')
                .to_string(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::{read_line, Line};
    use std::io::{BufReader, Cursor};

    #[test]
    fn reads_lines_and_eof() {
        let mut r = Cursor::new(b"one\ntwo\r\nthree".to_vec());
        assert_eq!(read_line(&mut r, 100).unwrap(), Line::Text("one".into()));
        assert_eq!(read_line(&mut r, 100).unwrap(), Line::Text("two".into()));
        assert_eq!(read_line(&mut r, 100).unwrap(), Line::Text("three".into()));
        assert_eq!(read_line(&mut r, 100).unwrap(), Line::Eof);
    }

    #[test]
    fn long_line_is_dropped_and_the_next_still_read() {
        let mut data = vec![b'x'; 1000];
        data.extend_from_slice(b"\nok\n");
        let mut r = Cursor::new(data);
        assert_eq!(read_line(&mut r, 10).unwrap(), Line::TooLong(1000));
        assert_eq!(read_line(&mut r, 10).unwrap(), Line::Text("ok".into()));
    }

    #[test]
    fn line_of_exactly_the_cap_is_kept() {
        let mut r = Cursor::new(b"abcde\nabcdef\n".to_vec());
        assert_eq!(read_line(&mut r, 5).unwrap(), Line::Text("abcde".into()));
        assert_eq!(read_line(&mut r, 5).unwrap(), Line::TooLong(6));
    }

    #[test]
    fn cap_holds_across_small_buffers() {
        let data = vec![b'y'; 5000];
        let mut r = BufReader::with_capacity(7, Cursor::new(data));
        assert_eq!(read_line(&mut r, 100).unwrap(), Line::TooLong(5000));
        assert_eq!(read_line(&mut r, 100).unwrap(), Line::Eof);
    }
}
