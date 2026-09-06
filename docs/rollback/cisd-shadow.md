# CISD shadow rollback

Set `enabled` to `false` in `config/cisd_shadow.json`. The lane has no broker,
notifier, execution, or sizing integration, so disabling the scanner is enough
to remove all runtime impact. Retain prior JSONL observations for auditability.
