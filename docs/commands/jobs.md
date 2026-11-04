# Jobs

Add API Reference

## Examples

- order by app
  - 'eai:acl.app="search"'
- order by author
  - 'eai:acl.owner="admin"' ou 'user=""'
- order by diskUsage
- order by runDuration

pour exporter au format raw, il faut avoir la clé \_raw dans la recherche
donc soit y'a pas d'agrégation (stats, tstats, table etc)
soit le champs \_raw est retourné

export - .csv - .json - .xslx - .txt/.log -> raw

## Submit and track ad hoc jobs

`spc jobs submit` dispatches search jobs without waiting for them. Each job is
recorded in `~/.spc/jobs.json` (label, SID, batch, instance, time range), so it
can be tracked later with `spc jobs status` / `spc jobs wait`, from any
directory. Jobs get a 7 days time-to-live by default (`--ttl`).

```bash
# one query
spc jobs submit '| makeresults count=10' -e -1h -l now --label test --batch demo

# a batch of searches declared in YAML
spc jobs submit -f examples/jobs/powerquery_limit.yml

# one-shot status (state, progress, result/event counts, job messages)
spc jobs status --batch pq-limit

# live table until every job is DONE, FAILED or cancelled
spc jobs wait --batch pq-limit --timeout 3600 --export ./results --output-format csv

# batches recorded in the registry
spc jobs batches
```

Without `--batch` nor SIDs, `status` and `wait` use the most recent batch. SIDs
that were not submitted with spc can be given as arguments too.

`wait` leaves failed or cancelled jobs aside and keeps tracking the others. At
the end it prints a summary with the job messages, and exits with code 1 if one
job is not `DONE`. Jobs still running at the timeout are reported `TIMEOUT` but
are not cancelled.

### Batch file

```yaml
batch: pq-limit                 # optional, overridden by --batch
defaults:                       # optional, applied to searches that omit them
  earliest: "1793707200"        # Splunk time modifier or epoch seconds
  latest: "1793710800"
  app: SOC                      # app namespace the job runs in
searches:
  - label: T1_limit_0_nolimit   # unique in the file
    query: >-
      | powerquery limit=0 debug=true usecase_id="LKP166"
      search="event.type = 'Process Creation' | columns agent.uuid"
      | stats count as rows_obtenues
  - label: T2_limit_1500000
    query: '...'
    latest: now                 # per-search override
```
