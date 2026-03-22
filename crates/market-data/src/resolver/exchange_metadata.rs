//! Exchange metadata lookups.
//!
//! This module provides lookup functions for exchange information
//! such as names, currencies, and currency-to-exchange mappings.
//! Data is loaded from `exchanges.json` via the exchange registry.

use chrono::{DateTime, Datelike, Duration, TimeZone, Utc, Weekday};
use chrono_tz::Tz;

use super::exchange_registry::REGISTRY;

/// Default grace period after market close before considering quotes stale.
const MARKET_CLOSE_GRACE_MINUTES: i64 = 60;

/// Get the friendly exchange name for a MIC code.
pub fn mic_to_exchange_name(mic: &str) -> Option<&'static str> {
    REGISTRY.name_by_mic.get(mic).copied()
}

/// Get the primary currency for a MIC code.
pub fn mic_to_currency(mic: &str) -> Option<&'static str> {
    REGISTRY.currency_by_mic.get(mic).copied()
}

/// Get the IANA timezone name for a MIC code.
pub fn mic_to_timezone(mic: &str) -> Option<&'static str> {
    REGISTRY.timezone_by_mic.get(mic).copied()
}

/// Get the market close time (hour, minute) for a MIC code.
pub fn mic_to_market_close(mic: &str) -> Option<(u8, u8)> {
    REGISTRY.close_by_mic.get(mic).copied()
}

/// Get the list of preferred exchanges for a given currency.
pub fn exchanges_for_currency(currency: &str) -> &'static [&'static str] {
    REGISTRY
        .currency_priority_slices
        .get(currency)
        .copied()
        .unwrap_or(&[])
}

/// Checks if the market is currently open or within trading hours.
///
/// Returns true if:
/// - It's a weekday AND
/// - Current local time is before market close + grace period
///
/// Unknown exchanges return true (conservative: assume open).
pub fn is_market_hours(now: DateTime<Utc>, mic: Option<&str>) -> bool {
    let (tz, close_time) = match mic
        .and_then(mic_to_timezone)
        .and_then(|tz_name| tz_name.parse::<Tz>().ok())
    {
        Some(tz) => (tz, mic.and_then(mic_to_market_close)),
        None => return true,
    };

    let local_now = now.with_timezone(&tz);
    let local_date = local_now.date_naive();

    let weekday = local_date.weekday();
    if weekday == Weekday::Sat || weekday == Weekday::Sun {
        return false;
    }

    let Some((close_hour, close_minute)) = close_time else {
        return true;
    };

    let Some(close_naive) = local_date.and_hms_opt(close_hour.into(), close_minute.into(), 0)
    else {
        return true;
    };

    let close_local = tz
        .from_local_datetime(&close_naive)
        .single()
        .or_else(|| tz.from_local_datetime(&close_naive).earliest())
        .or_else(|| tz.from_local_datetime(&close_naive).latest());

    let Some(close_local) = close_local else {
        return true;
    };

    let cutoff = close_local + Duration::minutes(MARKET_CLOSE_GRACE_MINUTES);
    local_now < cutoff
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn test_is_market_hours_false_for_weekends() {
        let saturday = Utc.with_ymd_and_hms(2026, 3, 21, 14, 0, 0).unwrap();
        assert!(!is_market_hours(saturday, Some("XNAS")));
    }

    #[test]
    fn test_is_market_hours_true_before_close() {
        let before_close = Utc.with_ymd_and_hms(2026, 3, 20, 18, 0, 0).unwrap();
        assert!(is_market_hours(before_close, Some("XNAS")));
    }

    #[test]
    fn test_is_market_hours_false_after_close_plus_grace() {
        let after_close = Utc.with_ymd_and_hms(2026, 3, 20, 22, 0, 0).unwrap();
        assert!(!is_market_hours(after_close, Some("XNAS")));
    }

    #[test]
    fn test_is_market_hours_true_for_unknown_exchange() {
        let anytime = Utc.with_ymd_and_hms(2026, 3, 20, 22, 0, 0).unwrap();
        assert!(is_market_hours(anytime, None));
        assert!(is_market_hours(anytime, Some("UNKNOWN")));
    }

    #[test]
    fn test_mic_to_exchange_name() {
        assert_eq!(mic_to_exchange_name("XNYS"), Some("NYSE"));
        assert_eq!(mic_to_exchange_name("XNAS"), Some("NASDAQ"));
        assert_eq!(mic_to_exchange_name("XTSE"), Some("TSX"));
        assert_eq!(mic_to_exchange_name("XLON"), Some("LSE"));
        assert_eq!(mic_to_exchange_name("CXE"), Some("Cboe UK"));
        assert_eq!(mic_to_exchange_name("XETR"), Some("XETRA"));
        assert_eq!(mic_to_exchange_name("UNKNOWN"), None);
    }

    #[test]
    fn test_mic_to_currency() {
        assert_eq!(mic_to_currency("XNYS"), Some("USD"));
        assert_eq!(mic_to_currency("XNAS"), Some("USD"));
        assert_eq!(mic_to_currency("XTSE"), Some("CAD"));
        assert_eq!(mic_to_currency("XLON"), Some("GBp")); // LSE quotes in pence
        assert_eq!(mic_to_currency("CXE"), Some("GBP"));
        assert_eq!(mic_to_currency("XETR"), Some("EUR"));
        assert_eq!(mic_to_currency("XTKS"), Some("JPY"));
        assert_eq!(mic_to_currency("UNKNOWN"), None);
    }

    #[test]
    fn test_exchanges_for_currency() {
        let us_exchanges = exchanges_for_currency("USD");
        assert!(us_exchanges.contains(&"XNYS"));
        assert!(us_exchanges.contains(&"XNAS"));

        let ca_exchanges = exchanges_for_currency("CAD");
        assert!(ca_exchanges.contains(&"XTSE"));
        assert!(ca_exchanges.contains(&"XTSX"));

        let unknown = exchanges_for_currency("XYZ");
        assert!(unknown.is_empty());
    }
}
