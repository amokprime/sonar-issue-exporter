# SonarQube Issues — amokprime_sonar-issue-exporter (main)

Generated: 2026-09-11 00:05 UTC
Source: `<no arg> (CWD repo: amokprime/sonar-issue-exporter main)`
Total: 6 issue(s) across 2 rule(s)
Token: clean (why/how sections suppressed)

---

## Summary

| Severity   | Count |   | Type          | Count |
|------------|-------|---|---------------|-------|
| CRITICAL   | 3     |  | VULNERABILITY | 3     |
| MAJOR      | 3     |  | CODE_SMELL    | 3     |

Top rules:
- `python:S3776` — 3×
- `shell:S8541` — 3×

---

## Rule: `python:S3776` — python:S3776

Severity: CRITICAL: 3 · Type: CODE_SMELL: 3 · CleanCode: FOCUSED: 3 · 3 instance(s)

### Instances

| File | Line | Message | Key | Status |
|------|------|---------|-----|--------|
| `sie.py` | L562 | Refactor this function to reduce its Cognitive Complexity from 19 to the 15 allowed. | `AaCNwmWO1WTeVOIYASKs` | OPEN |
| `sie.py` | L1568 | Refactor this function to reduce its Cognitive Complexity from 18 to the 15 allowed. | `AaCNwmWO1WTeVOIYASKt` | OPEN |
| `sie.py` | L1711 | Refactor this function to reduce its Cognitive Complexity from 16 to the 15 allowed. | `AaCNwmWO1WTeVOIYASKu` | OPEN |

Deep links: `https://sonarcloud.io/project/issues?open=<KEY>&id=amokprime_sonar-issue-exporter`

---

## Rule: `shell:S8541` — shell:S8541

Severity: MAJOR: 3 · Type: VULNERABILITY: 3 · CleanCode: TRUSTWORTHY: 3 · 3 instance(s)

### Instances

| File | Line | Message | Key | Status |
|------|------|---------|-----|--------|
| `ai/chat.z.ai/scripts/delivery/deploy.sh` | L206 | Omitting "--no-build" can lead to the execution of setup scripts. Make sure it is safe here. | `AaCNwmTt1WTeVOIYASKp` | OPEN |
| `ai/chat.z.ai/scripts/delivery/deploy.sh` | L213 | Omitting "--no-build" can lead to the execution of setup scripts. Make sure it is safe here. | `AaCNwmTt1WTeVOIYASKq` | OPEN |
| `ai/chat.z.ai/scripts/delivery/deploy.sh` | L214 | Omitting "--no-build" can lead to the execution of setup scripts. Make sure it is safe here. | `AaCNwmTt1WTeVOIYASKr` | OPEN |

Deep links: `https://sonarcloud.io/project/issues?open=<KEY>&id=amokprime_sonar-issue-exporter`

---
